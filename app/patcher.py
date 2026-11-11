"""Diff önizleme, doğrulama, atomik yazma ve geri alma araçları.

Uyumluluk:
    compute_hash(text)
    generate_diff(original_text, updated_text, filename="file")
    colorize_diff(diff_text)
    safe_apply_patch(filepath, new_content, original_hash=None, auto_approve=False)

Ek işlev:
    rollback_patch(filepath, expected_hash=None, auto_approve=False)

Not:
    Hash hesabı, önceki sürümle uyum için UTF-8 olarak kodlanmış
    metnin SHA-256 özetidir. Dosyadan hesaplanan hash'lerde evrensel
    satır sonu dönüşümü uygulanır: CRLF ve CR, LF olarak değerlendirilir.
"""

import codecs
import difflib
import hashlib
import io
import os
import stat
import tempfile
import tokenize
from pathlib import Path
from typing import Optional, Tuple


def compute_hash(text: str) -> str:
    """Bir metnin SHA-256 özetini hesapla."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_newlines(text: str) -> str:
    """Python'un evrensel satır sonu okuma davranışını uygula."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _decode_utf8(data: bytes) -> str:
    """İçeriği kayıpsız olarak UTF-8 çöz; geçersiz baytları reddet."""
    return data.decode("utf-8", errors="strict")


def _content_hash(data: bytes) -> str:
    """Eski sürümün metin tabanlı hash hesabıyla uyumlu özet üret."""
    return compute_hash(_normalize_newlines(_decode_utf8(data)))


def _detect_newline(text: str) -> str:
    """Baskın satır sonunu seç; satır sonu yoksa LF kullan."""
    crlf = text.count("\r\n")
    remaining = text.replace("\r\n", "")
    lf = remaining.count("\n")
    cr = remaining.count("\r")

    counts = {"\r\n": crlf, "\n": lf, "\r": cr}
    if not any(counts.values()):
        return "\n"

    return max(counts, key=counts.get)


def _prepare_content(current_bytes: bytes, new_content: str) -> bytes:
    """Yeni içeriği mevcut dosyanın baskın satır sonuyla UTF-8 kodla.

    Mevcut dosyada UTF-8 BOM varsa ve yeni içerikte yoksa BOM korunur.
    Karışık satır sonları baskın türde birleştirilir.
    """
    current_text = _decode_utf8(current_bytes)
    newline = _detect_newline(current_text)

    normalized = _normalize_newlines(new_content)

    if current_text.startswith("\ufeff") and not normalized.startswith("\ufeff"):
        normalized = "\ufeff" + normalized

    if newline != "\n":
        normalized = normalized.replace("\n", newline)

    return normalized.encode("utf-8", errors="strict")


def generate_diff(
    original_text: str,
    updated_text: str,
    filename: str = "file",
) -> str:
    """İki metin arasında unified diff üret."""
    original_lines = original_text.splitlines(keepends=True)
    updated_lines = updated_text.splitlines(keepends=True)

    return "".join(
        difflib.unified_diff(
            original_lines,
            updated_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            n=3,
        )
    )


def colorize_diff(diff_text: str) -> str:
    """Unified diff metnini ANSI renk kodlarıyla biçimlendir."""
    colored_lines = []

    for line in diff_text.splitlines():
        if line.startswith(("+++", "---")):
            colored_lines.append(f"\033[1;37m{line}\033[0m")
        elif line.startswith("@@"):
            colored_lines.append(f"\033[36m{line}\033[0m")
        elif line.startswith("+"):
            colored_lines.append(f"\033[32m{line}\033[0m")
        elif line.startswith("-"):
            colored_lines.append(f"\033[31m{line}\033[0m")
        else:
            colored_lines.append(line)

    return "\n".join(colored_lines)


def _print_diff(filepath: Path, old_bytes: bytes, new_bytes: bytes) -> None:
    """Diff önizlemesini terminale yaz."""
    old_text = _normalize_newlines(_decode_utf8(old_bytes))
    new_text = _normalize_newlines(_decode_utf8(new_bytes))
    diff_text = generate_diff(old_text, new_text, filename=filepath.name)

    print("\n" + "=" * 55)
    print(f"      ÖNERİLEN DEĞİŞİKLİKLER ({filepath})")
    print("=" * 55)

    if diff_text:
        print(colorize_diff(diff_text))
    else:
        print("(Metinsel diff yok; yalnızca bayt gösterimi değişiyor.)")

    print("=" * 55 + "\n")


def _confirm(prompt: str) -> bool:
    """Yalnızca açık bir evet yanıtını kabul et."""
    try:
        answer = input(prompt).strip().lower()
    except (KeyboardInterrupt, EOFError):
        return False

    return answer in ("e", "evet", "y", "yes")


def _read_regular_file(filepath: Path) -> bytes:
    """Sembolik bağlantıları ve düzenli olmayan dosyaları reddederek oku."""
    file_stat = filepath.stat(follow_symlinks=False)

    if stat.S_ISLNK(file_stat.st_mode):
        raise ValueError(f"Sembolik bağlantı desteklenmiyor: {filepath}")

    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError(f"Düzenli dosya değil: {filepath}")

    return filepath.read_bytes()


def _validate_python(filepath: Path, data: bytes) -> Optional[str]:
    """Python kaynak kodunu çalıştırmadan derle ve syntax kontrolü yap."""
    if filepath.suffix.lower() not in (".py", ".pyw"):
        return None

    try:
        detected_encoding, _ = tokenize.detect_encoding(
            io.BytesIO(data).readline
        )
        canonical_encoding = codecs.lookup(detected_encoding).name

        if canonical_encoding not in ("utf-8", "utf-8-sig"):
            return (
                "Python dosyasının kodlama bildirimi UTF-8 olmalı: "
                f"{detected_encoding}"
            )

        compile(
            data,
            str(filepath),
            "exec",
            dont_inherit=True,
        )
    except (SyntaxError, UnicodeError, LookupError, ValueError) as exc:
        if isinstance(exc, SyntaxError):
            line = exc.lineno if exc.lineno is not None else "?"
            column = exc.offset if exc.offset is not None else "?"
            return f"Syntax hatası (satır {line}, sütun {column}): {exc.msg}"

        return f"Python doğrulama hatası: {exc}"

    return None


def _make_temp_file(
    destination: Path,
    data: bytes,
    mode: int,
) -> Path:
    """Hedefle aynı dizinde içeriği diske yazılmış geçici dosya oluştur."""
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "wb") as temp_file:
            temp_file.write(data)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.chmod(temp_path, stat.S_IMODE(mode))
        return temp_path
    except BaseException:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _remove_temp(path: Optional[Path]) -> None:
    """Geçici dosyayı en iyi çabayla temizle."""
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _atomic_replace(destination: Path, data: bytes, mode: int) -> None:
    """Hedefi aynı dizindeki geçici dosyadan atomik olarak değiştir."""
    temp_path = _make_temp_file(destination, data, mode)
    try:
        os.replace(temp_path, destination)
    finally:
        _remove_temp(temp_path)


def safe_apply_patch(
    filepath: str,
    new_content: str,
    original_hash: Optional[str] = None,
    auto_approve: bool = False,
) -> Tuple[bool, str]:
    """Değişikliği önizle, doğrula, yedekle ve atomik olarak uygula."""
    path = Path(filepath)
    backup_path = Path(f"{filepath}.bak")
    temp_path = None

    try:
        current_bytes = _read_regular_file(path)
        current_text = _decode_utf8(current_bytes)
        current_hash = compute_hash(_normalize_newlines(current_text))

        if original_hash is not None and current_hash != original_hash:
            return False, (
                f"Güvenlik uyarısı: '{path}' dosyası öneri üretilirken "
                "değişmiş. Çakışmayı önlemek için işlem durduruldu."
            )

        proposed_bytes = _prepare_content(current_bytes, new_content)

        if current_bytes == proposed_bytes:
            return True, "Dosya içeriğinde herhangi bir değişiklik yok."

        validation_error = _validate_python(path, proposed_bytes)
        if validation_error:
            return False, f"Değişiklik uygulanmadı. {validation_error}"

        _print_diff(path, current_bytes, proposed_bytes)

        if not auto_approve and not _confirm(
            f"Bu değişiklikler '{path}' dosyasına uygulansın mı? [e/H]: "
        ):
            return False, "İşlem iptal edildi; dosya güncellenmedi."

        # Kullanıcı onayı beklenirken dosya değişmiş olabilir.
        if _read_regular_file(path) != current_bytes:
            return False, (
                f"Güvenlik uyarısı: '{path}' önizlemeden sonra değişti. "
                "İşlem durduruldu."
            )

        file_mode = path.stat(follow_symlinks=False).st_mode

        # Yedek de atomik olarak yazılır; mevcut .bak dosyası değiştirilir.
        if backup_path.is_symlink():
            return False, f"Yedek yolu sembolik bağlantı: {backup_path}"

        _atomic_replace(backup_path, current_bytes, file_mode)

        # Yeni dosya atomik olarak uygulanır
        temp_path = _make_temp_file(path, proposed_bytes, file_mode)

        if _read_regular_file(path) != current_bytes:
            return False, (
                f"Güvenlik uyarısı: '{path}' işlem sırasında değişti. "
                f"Dosya güncellenmedi; alınan yedek: {backup_path}"
            )

        os.replace(temp_path, path)
        temp_path = None

        applied_hash = _content_hash(proposed_bytes)
        return True, (
            f"✓ '{path}' başarıyla güncellendi.\n"
            f"  Yedek: '{backup_path}'\n"
            f"  Yeni Hash: {applied_hash[:16]}..."
        )

    except FileNotFoundError as exc:
        return False, f"Dosya veya dizin bulunamadı: {exc.filename or path}"
    except UnicodeError as exc:
        return False, f"UTF-8 kodlama hatası; işlem uygulanmadı: {exc}"
    except (OSError, ValueError, TypeError) as exc:
        return False, f"İşlem uygulanamadı: {exc}"
    finally:
        _remove_temp(temp_path)


def rollback_patch(
    filepath: str,
    expected_hash: Optional[str] = None,
    auto_approve: bool = False,
) -> Tuple[bool, str]:
    """`.bak` dosyasını güvenli biçimde geri yükle."""
    path = Path(filepath)
    backup_path = Path(f"{filepath}.bak")
    temp_path = None

    try:
        current_bytes = _read_regular_file(path)
        backup_bytes = _read_regular_file(backup_path)

        current_hash = _content_hash(current_bytes)

        if expected_hash and current_hash != expected_hash:
            return False, (
                f"Güvenlik uyarısı: '{path}' beklenen sürüm değil. "
                "Sonraki değişiklikleri korumak için geri alma durduruldu."
            )

        _decode_utf8(backup_bytes)

        if current_bytes == backup_bytes:
            return True, "Dosya zaten yedekle aynı; geri alma gerekmedi."

        _print_diff(path, current_bytes, backup_bytes)

        if not auto_approve and not _confirm(
            f"'{backup_path}' yedeği '{path}' üzerine geri yüklensin mi? [e/H]: "
        ):
            return False, "Geri alma iptal edildi."

        if _read_regular_file(path) != current_bytes:
            return False, (
                f"Güvenlik uyarısı: '{path}' önizlemeden sonra değişti. "
                "Geri alma durduruldu."
            )

        file_mode = path.stat(follow_symlinks=False).st_mode
        temp_path = _make_temp_file(path, backup_bytes, file_mode)

        if _read_regular_file(path) != current_bytes:
            return False, (
                f"Güvenlik uyarısı: '{path}' geri alma sırasında değişti. "
                "İşlem durduruldu."
            )

        os.replace(temp_path, path)
        temp_path = None

        return True, (
            f"✓ '{path}' yedekten geri yüklendi.\n"
            f"  Yedek korundu: '{backup_path}'\n"
            f"  Geri yüklenen Hash: {_content_hash(backup_bytes)[:16]}..."
        )

    except FileNotFoundError as exc:
        return False, f"Dosya veya yedek bulunamadı: {exc.filename or path}"
    except UnicodeError as exc:
        return False, f"UTF-8 kodlama hatası; geri alma uygulanmadı: {exc}"
    except (OSError, ValueError, TypeError) as exc:
        return False, f"Geri alma uygulanamadı: {exc}"
    finally:
        _remove_temp(temp_path)
