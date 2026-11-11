import ast
import inspect
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from app.notion_client import NotionOpusAPI
from app.conversation import ConversationManager
from app.tools import TOOLS_REGISTRY, TOOL_SYSTEM_PROMPT


MAX_CALL_CHARS = 32_000
MAX_MODEL_OUTPUT_CHARS = 120_000
MAX_RESULT_PROMPT_CHARS = 80_000
MAX_CONSECUTIVE_ERRORS = 3

TOOL_CALL_REGEX = re.compile(
    r"""<tool_call\s+name\s*=\s*(["'])([A-Za-z_][A-Za-z0-9_]*)\1\s*>"""
    r"""([\s\S]*?)</tool_call\s*>""",
    re.IGNORECASE,
)

FENCE_REGEX = re.compile(
    r"^\s*```(?:json|python)?\s*\n([\s\S]*?)\n```\s*$",
    re.IGNORECASE,
)


class CallParseError(ValueError):
    pass


def _reject_duplicate_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Tekrarlanan JSON anahtarı: {key}")
        result[key] = value
    return result


def _is_json_value(value: Any, depth: int = 0) -> bool:
    """literal_eval sonucunu yalnızca JSON benzeri değerlere sınırla."""
    if depth > 20:
        return False
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return value == value and abs(value) != float("inf")
    if isinstance(value, list):
        return all(_is_json_value(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item, depth + 1)
            for key, item in value.items()
        )
    return False


def _parse_arguments(raw: str) -> Dict[str, Any]:
    raw = raw.strip()

    if len(raw) > MAX_CALL_CHARS:
        raise CallParseError("Araç argümanları boyut sınırını aşıyor.")

    fence = FENCE_REGEX.fullmatch(raw)
    if fence:
        raw = fence.group(1).strip()

    if not raw:
        return {}

    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"Geçersiz JSON sabiti: {token}")
            ),
        )
    except (json.JSONDecodeError, ValueError, RecursionError):
        # Python tarzı tek tırnaklı sözlükleri destekle
        try:
            tree = ast.parse(raw, mode="eval")
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    keys = []
                    for key_node in node.keys:
                        if not isinstance(key_node, ast.Constant):
                            raise ValueError("Sözlük anahtarı sabit olmalı.")
                        key = key_node.value
                        if not isinstance(key, str) or key in keys:
                            raise ValueError(
                                "Sözlük anahtarları benzersiz metin olmalı."
                            )
                        keys.append(key)
            value = ast.literal_eval(tree)
        except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
            raise CallParseError(
                "Argümanlar ayrıştırılamadı. JSON nesnesi gönder; "
                'örnek: {"path": "app/tools.py"}. Ham metin kabul edilmez.'
            ) from None

    if not isinstance(value, dict):
        raise CallParseError(
            "Araç argümanları bir nesne/sözlük olmalı; liste veya metin değil."
        )

    if not _is_json_value(value):
        raise CallParseError(
            "Yalnızca JSON uyumlu değerler ve makul iç içe geçme kabul edilir."
        )

    return value


def _parse_call(output: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    matches = list(TOOL_CALL_REGEX.finditer(output))
    lowered = output.lower()

    # Eksik veya bozuk etiketleri nihai yanıt sanma.
    open_count = lowered.count("<tool_call")
    close_count = lowered.count("</tool_call")

    if open_count == 0 and close_count == 0:
        return None

    if len(matches) != 1 or open_count != 1 or close_count != 1:
        raise CallParseError(
            "Tam ve geçerli biçimde yalnızca bir tool_call gönder. "
            'Örnek: <tool_call name="read_file">'
            '{"path":"app/tools.py"}</tool_call>.'
        )

    match = matches[0]
    return match.group(2), _parse_arguments(match.group(3))


def _error(code: str, message: str, hint: str) -> Dict[str, Any]:
    return {"ok": False, "code": code, "message": message, "hint": hint}


def _execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    fn = TOOLS_REGISTRY.get(name)
    if fn is None:
        return _error(
            "UNKNOWN_TOOL",
            f"Bilinmeyen araç: {name}",
            "Kullanılabilir araçlar: " + ", ".join(TOOLS_REGISTRY),
        )

    try:
        signature = inspect.signature(fn)
        signature.bind(**args)
    except TypeError as exc:
        return _error(
            "INVALID_ARGUMENTS",
            str(exc),
            f"Beklenen imza: {name}{signature}. "
            "Parametre adlarını ve zorunlu alanları düzelt.",
        )
    except (ValueError, AttributeError) as exc:
        return _error(
            "SIGNATURE_ERROR",
            str(exc),
            "Araç kaydını kontrol et.",
        )

    try:
        raw_result = fn(**args)
    except Exception as exc:
        return _error(
            "TOOL_EXCEPTION",
            f"{type(exc).__name__}: {exc}",
            "Hatayı ve parametreleri incele.",
        )

    if isinstance(raw_result, str):
        try:
            result = json.loads(raw_result)
        except json.JSONDecodeError:
            return _error(
                "UNSTRUCTURED_RESULT",
                raw_result[:10_000],
                "Araç yapılandırılmış sonuç döndürmedi.",
            )
    elif isinstance(raw_result, dict):
        result = raw_result
    else:
        return _error(
            "INVALID_TOOL_RESULT",
            f"Beklenmeyen sonuç türü: {type(raw_result).__name__}",
            "Araç uygulamasını kontrol et.",
        )

    if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
        return _error(
            "INVALID_TOOL_RESULT",
            "Araç sonucu boolean ok alanı içermiyor.",
            "Araç uygulamasını yapılandırılmış sonuç döndürecek şekilde düzelt.",
        )

    return result


def _feedback_prompt(
    tool_name: str,
    result: Dict[str, Any],
) -> str:
    payload = json.dumps(
        {"tool": tool_name, "result": result},
        ensure_ascii=False,
        default=str,
    )

    if len(payload) > MAX_RESULT_PROMPT_CHARS:
        payload = json.dumps(
            {
                "tool": tool_name,
                "result": _error(
                    "RESULT_TOO_LARGE",
                    "Araç sonucu bağlam bütçesini aştı.",
                    "Daha küçük bir aralık veya daha dar bir arama kullan.",
                ),
            },
            ensure_ascii=False,
        )

    return (
        "Araç geri bildirimi aşağıdadır:\n"
        f"{payload}\n\n"
        "ok=false ise hatayı düzelt. Başarılıysa sonraki adımı seç veya "
        "işlem sonucunu doğrulayıp nihai yanıt ver."
    )


def run_agent_loop(
    client: NotionOpusAPI,
    manager: ConversationManager,
    conv_id: str,
    user_goal: str,
    model_name: str = "claude-opus4.6",
    max_steps: int = 10,
    show_thinking: bool = False,
) -> str:
    """
    Model -> tek araç -> yapılandırılmış geri bildirim döngüsü.
    """
    if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
        raise ValueError("max_steps pozitif bir tam sayı olmalı.")

    current_prompt = f"{TOOL_SYSTEM_PROMPT}\n\nKullanıcı Görevi: {user_goal}"
    consecutive_errors = 0
    last_error_fingerprint: Optional[str] = None
    last_output = ""

    print("\n" + "=" * 55)
    print("      OTONOM AJAN DÖNGÜSÜ BAŞLATILDI (ReAct)      ")
    print(f" Hedef: {user_goal}")
    print("=" * 55 + "\n")

    for step in range(1, max_steps + 1):
        print(f"\033[1;34m[Adım {step}/{max_steps}]\033[0m Ajan düşünüyor...")

        try:
            transcript = manager.get_transcript(
                client, conv_id, current_prompt, model_name
            )

            parts: List[str] = []
            output_length = 0

            for chunk in client.stream_response(transcript):
                text = ""

                if isinstance(chunk, dict):
                    kind = chunk.get("type")
                    chunk_text = chunk.get("text", "")

                    if not isinstance(chunk_text, str):
                        continue

                    if kind == "thinking":
                        if show_thinking:
                            print(f"\033[90m{chunk_text}\033[0m", end="", flush=True)
                    elif kind == "content":
                        text = chunk_text
                    elif kind == "final_content" and not parts:
                        text = chunk_text

                elif isinstance(chunk, str):
                    text = chunk

                if text:
                    output_length += len(text)
                    if output_length > MAX_MODEL_OUTPUT_CHARS:
                        return (
                            "İşlem tamamlanmadı: model çıktısı boyut sınırını aştı."
                        )
                    parts.append(text)
                    print(text, end="", flush=True)

            print()
            step_output = "".join(parts)
            last_output = step_output

        except Exception as exc:
            return (
                "İşlem tamamlanmadı: model akışı veya konuşma yönetimi "
                f"hatası ({type(exc).__name__}: {exc})."
            )

        try:
            manager.persist_round(conv_id, current_prompt, step_output)
        except Exception as exc:
            return (
                "İşlem durduruldu: konuşma turu kaydedilemedi "
                f"({type(exc).__name__}: {exc})."
            )

        if not step_output.strip():
            result = _error(
                "EMPTY_MODEL_OUTPUT",
                "Model boş çıktı üretti.",
                "Geçerli bir araç çağrısı veya nihai yanıt üret.",
            )
            tool_name = "parser"
            fingerprint = "EMPTY_MODEL_OUTPUT"
        else:
            try:
                parsed = _parse_call(step_output)
            except CallParseError as exc:
                result = _error(
                    "MALFORMED_TOOL_CALL",
                    str(exc),
                    "Tek bir geçerli tool_call ve JSON nesnesi gönder.",
                )
                tool_name = "parser"
                fingerprint = "MALFORMED_TOOL_CALL:" + step_output[:2_000]
            else:
                if parsed is None:
                    print("\n\033[1;32m[Görev döngüsü tamamlandı]\033[0m")
                    return step_output

                tool_name, args = parsed
                print(f"\n\033[1;33m[Araç Çağrısı]\033[0m {tool_name}({args})")
                result = _execute_tool(tool_name, args)

                fingerprint = json.dumps(
                    {"tool": tool_name, "args": args},
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )

        status_color = "\033[32m" if result.get("ok") else "\033[31m"
        print(
            f"\033[1;36m[Araç Sonucu]\033[0m {status_color}ok={result.get('ok')}\033[0m "
            f"code={result.get('code', 'UNKNOWN')}"
        )

        if result.get("ok") is False:
            consecutive_errors += 1

            if fingerprint == last_error_fingerprint:
                return (
                    "İşlem tamamlanmadı: aynı başarısız çağrı tekrarlandı. "
                    "Tekrar durduruldu; hata: "
                    + json.dumps(result, ensure_ascii=False, default=str)
                )

            last_error_fingerprint = fingerprint

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                return (
                    "İşlem tamamlanmadı: art arda hata sınırına ulaşıldı. "
                    "Son hata: "
                    + json.dumps(result, ensure_ascii=False, default=str)
                )
        else:
            consecutive_errors = 0
            last_error_fingerprint = None

        current_prompt = _feedback_prompt(tool_name, result)

    return (
        f"İşlem tamamlanmadı: {max_steps} adımlık sınıra ulaşıldı. "
        "Son model çıktısı:\n"
        + last_output[:10_000]
    )
