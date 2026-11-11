import sys
import os
import re
import argparse
import subprocess
import shutil

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Suppress noisy JSON logging on terminal CLI by default
os.environ.setdefault("NOTION_CLI_MODE", "1")

from app.config import get_default_account
from app.notion_client import NotionOpusAPI
from app.conversation import ConversationManager
from app.model_registry import MODEL_MAP, list_available_models, get_display_name
from app.patcher import safe_apply_patch, rollback_patch, compute_hash
from app.agent_loop import run_agent_loop
from app.task_queue import create_task, list_tasks, run_worker_cycle

SESSION_FILE = os.path.join(BASE_DIR, "data", "cli_session.txt")

MODEL_ALIASES = {
    "auto": "auto",
    "default": "auto",
    "sonnet": "claude-sonnet4.6",
    "sonnet5": "claude-sonnet5",
    "sonnet5.5": "claude-sonnet5.5",
    "opus": "claude-opus4.6",
    "opus5": "claude-opus5",
    "haiku": "claude-haiku4.5",
    "gpt": "gpt-5.5",
    "gpt5": "gpt-5.5",
    "gpt6": "gpt-6.1-sol",
    "gemini": "gemini-3.5flash",
    "gemini-pro": "gemini-3.1pro",
    "deepseek": "deepseek-v4pro",
    "deepseek-flash": "deepseek-v4flash",
    "kimi": "kimi-2.7",
}

def resolve_model(model_input: str) -> str:
    if not model_input:
        return "auto"
    lower = model_input.lower().strip()
    if lower in MODEL_ALIASES:
        return MODEL_ALIASES[lower]
    if lower in MODEL_MAP:
        return lower
    for k in MODEL_MAP:
        if lower in k:
            return k
    return "auto"

def get_or_create_conversation(manager: ConversationManager, force_new: bool = False) -> str:
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    if not force_new and os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                conv_id = f.read().strip()
            with manager._get_conn() as conn:
                row = conn.execute("SELECT id FROM conversations WHERE id = ?", (conv_id,)).fetchone()
                if row:
                    return conv_id
        except Exception:
            pass
    
    conv_id = manager.new_conversation()
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            f.write(conv_id)
    except Exception:
        pass
    return conv_id

def has_stdin_data() -> bool:
    """Non-blocking check whether stdin has bytes waiting to be read."""
    if sys.stdin.isatty():
        return False
    try:
        import msvcrt
        import ctypes
        from ctypes import wintypes
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        avail = wintypes.DWORD()
        res = ctypes.windll.kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(avail), None)
        return bool(res and avail.value > 0)
    except Exception:
        return False

def extract_code_block(text: str) -> str:
    """Extract code content from markdown code block if present."""
    match = re.search(r"```(?:\w+)?\n([\s\S]*?)```", text)
    if match:
        return match.group(1).rstrip()
    return text.strip()

def save_to_notion(title: str, content: str) -> bool:
    """Save content to Notion workspace using ntn CLI via stdin pipe."""
    md_content = f"# {title}\n\n{content}"
    try:
        env = dict(os.environ)
        env["NOTION_KEYRING"] = "0"
        result = subprocess.run(
            ["ntn", "pages", "create"],
            input=md_content,
            capture_output=True,
            text=True,
            shell=True,
            env=env
        )
        if result.returncode == 0:
            page_id = result.stdout.strip()
            print(f"\n\033[1;32m[Notion]\033[0m ✓ '{title}' başlıklı sayfa Notion çalışma alanınıza kaydedildi (ID: {page_id}).")
            return True
        else:
            print(f"\n[Notion Uyarısı] Sayfa kaydedilemedi: {result.stderr.strip() or result.stdout.strip()}")
            return False
    except Exception as e:
        print(f"\n[Notion Hatası] {e}")
        return False

def ask_notion(
    prompt: str,
    model_name: str = "auto",
    force_new: bool = False,
    show_thinking: bool = False,
    edit_file: str = None,
    save_title: str = None,
    auto_approve: bool = False,
):
    actual_model = resolve_model(model_name)
    try:
        account = get_default_account()
    except RuntimeError as e:
        print(f"\033[1;31m[Hata]\033[0m {e}")
        sys.exit(1)
    client = NotionOpusAPI(account)
    manager = ConversationManager()
    
    conv_id = get_or_create_conversation(manager, force_new=force_new)
    
    original_code = ""
    original_hash = None
    if edit_file:
        if not os.path.exists(edit_file):
            print(f"\033[1;31m[Hata]\033[0m Düzenlenecek dosya bulunamadı: {edit_file}")
            sys.exit(1)
        with open(edit_file, "r", encoding="utf-8", errors="replace") as f:
            original_code = f.read()
        original_hash = compute_hash(original_code)
        
        prompt = (
            f"Kullanıcı '{edit_file}' dosyasını güncellemeni istiyor.\n\n"
            f"--- MEVCUT DOSYA İÇERİĞİ ({edit_file}) ---\n"
            f"```\n{original_code}\n```\n\n"
            f"--- KULLANICI İSTEĞİ ---\n{prompt}\n\n"
            f"LÜTFEN DİKKAT: Dosyanın güncellenmiş ve eksiksiz halini bir ```kod bloğu``` içinde sun. "
            f"Kodu parçalamadan, doğrudan dosyaya yazılabilecek tam haliyle ver."
        )

    transcript = manager.get_transcript(client, conv_id, prompt, actual_model)
    
    full_output = ""
    thinking_buffer = ""
    
    for chunk in client.stream_response(transcript):
        if isinstance(chunk, dict):
            ctype = chunk.get("type")
            if ctype == "thinking" and show_thinking:
                t_text = chunk.get("text", "")
                thinking_buffer += t_text
                print(f"\033[90m{t_text}\033[0m", end="", flush=True)
            elif ctype == "content":
                if thinking_buffer:
                    print("\n", flush=True)
                    thinking_buffer = ""
                text = chunk.get("text", "")
                print(text, end="", flush=True)
                full_output += text
            elif ctype == "final_content":
                if not full_output:
                    text = chunk.get("text", "")
                    print(text, end="", flush=True)
                    full_output += text
        elif isinstance(chunk, str) and chunk:
            print(chunk, end="", flush=True)
            full_output += chunk
    print()

    # Save to sliding window memory
    if full_output:
        try:
            manager.persist_round(conv_id, prompt, full_output)
        except Exception:
            pass

    # Pillar 1: Safe Patching with Diff Review & Hash Check
    if edit_file and full_output:
        new_code = extract_code_block(full_output)
        success, msg = safe_apply_patch(
            filepath=edit_file,
            new_content=new_code,
            original_hash=original_hash,
            auto_approve=auto_approve
        )
        print(f"\n{msg}")

    # Save to Notion
    if save_title and full_output:
        save_to_notion(save_title, full_output)

def interactive_loop(args):
    """Canlı interaktif terminal REPL sohbet oturumu."""
    try:
        get_default_account()
    except RuntimeError as e:
        print(f"\033[1;31m[Hata]\033[0m {e}")
        sys.exit(1)

    manager = ConversationManager()
    actual_model = resolve_model(args.model)
    get_or_create_conversation(manager, force_new=args.new)
    display_model = get_display_name(actual_model)

    print("=" * 60)
    print("       NOTION AI İNTERAKTİF SOHBET KONSOLU")
    print(f"       Model: {display_model} ({actual_model})")
    print("=" * 60)
    print("İpuçları:")
    print("  • Çıkış için: 'exit', 'quit' veya 'q'")
    print("  • Sohbeti sıfırlamak için: 'new' veya 'reset'")
    print("  • Model değiştirmek için: '/model <ad>' (örn: /model sonnet)")
    print("  • Oturum durumu: '/whoami' veya '/status'")
    print("-" * 60 + "\n")

    while True:
        try:
            user_input = input("\033[1;36mSen > \033[0m").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nOturum sonlandırıldı.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "q"):
            print("Görüşmek üzere!")
            break

        if user_input.lower() in ("new", "reset"):
            get_or_create_conversation(manager, force_new=True)
            print("\n--- Yeni Sohbet Oturumu Başlatıldı ---\n")
            continue

        if user_input.lower() in ("/whoami", "/status", "whoami", "status"):
            show_auth_status()
            continue

        if user_input.lower() in ("/logout", "logout"):
            perform_logout()
            break

        if user_input.lower() in ("/models", "models"):
            print_models()
            continue

        if user_input.startswith("/model "):
            new_model = user_input.split(maxsplit=1)[1].strip()
            actual_model = resolve_model(new_model)
            display_model = get_display_name(actual_model)
            print(f"\n[Model Değiştirildi] -> {display_model} ({actual_model})\n")
            continue

        print(f"\n\033[1;32mNotion AI ({display_model}) > \033[0m", end="", flush=True)
        ask_notion(
            prompt=user_input,
            model_name=actual_model,
            force_new=False,
            show_thinking=args.think,
            edit_file=None,
            save_title=None,
            auto_approve=args.yes,
        )
        print()

def show_auth_status() -> int:
    from app.config import load_accounts
    accounts = load_accounts()
    if not accounts:
        print("\n\033[1;33m[VoyagerRelay Auth Durumu]\033[0m")
        print("✗ Henüz bağlı bir Notion hesabı bulunamadı.")
        print("Giriş yapmak için:")
        print("  voyager-relay login")
        print("  (veya manuel: voyager-relay login --manual)\n")
        return 1

    account = accounts[0]
    user_name = account.get("user_name") or "Bilinmiyor"
    user_email = account.get("user_email") or "Bilinmiyor"
    space_id = account.get("space_id") or "Bilinmiyor"
    profile = account.get("profile_name") or "default"

    print("\n\033[1;32m[VoyagerRelay Auth Durumu]\033[0m")
    print(f"✓ Aktif Profil : {profile}")
    print(f"  Kullanıcı     : {user_name} ({user_email})")
    print(f"  Workspace ID  : {space_id}")
    print(f"  Toplam Profil : {len(accounts)}")
    print(f"  Durum         : Bağlı ve aktif (Tüm sorgular $0 maliyetle akar)\n")
    return 0

def perform_logout() -> int:
    accounts_file = os.path.join(BASE_DIR, "accounts.json")
    env_file = os.path.join(BASE_DIR, ".env")
    session_file = SESSION_FILE

    cleared = False
    if os.path.exists(accounts_file):
        try:
            os.remove(accounts_file)
            cleared = True
        except Exception as e:
            print(f"[Uyarı] accounts.json silinemedi: {e}")

    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new_lines = [line for line in lines if not line.startswith("NOTION_ACCOUNTS=")]
            with open(env_file, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            cleared = True
        except Exception as e:
            print(f"[Uyarı] .env güncellenemedi: {e}")

    if os.path.exists(session_file):
        try:
            os.remove(session_file)
        except Exception:
            pass

    if cleared:
        print("\n\033[1;32m[VoyagerRelay]\033[0m Başarıyla çıkış yapıldı.")
        print("Kayıtlı Notion hesap bilgileri ve oturum temizlendi.")
        print("Yeniden bağlanmak için: voyager-relay login\n")
    else:
        print("\n[VoyagerRelay] Zaten aktif bir giriş bulunmuyor veya hesap bilgisi temiz.\n")
    return 0

def print_models():
    print("=" * 50)
    print("       NOTION AI DESTEKLENEN MODELLER        ")
    print("=" * 50)
    print("\n[Kullanışlı Kısayollar]:")
    for alias, target in MODEL_ALIASES.items():
        print(f"  --model {alias:<14} -> {target}")
    print("\n[Mevcut Tüm Modeller]:")
    for m in list_available_models():
        print(f"  • {m:<20} ({get_display_name(m)})")
    print("\nÖrnek: notion-ai -m sonnet \"Kodu optimize et\"")

def main():
    if len(sys.argv) > 1:
        subcmd = sys.argv[1].lower()
        if subcmd == "login":
            import login
            sys.exit(login.main(sys.argv[2:]))
        elif subcmd in ("whoami", "status", "auth"):
            sys.exit(show_auth_status())
        elif subcmd == "logout":
            sys.exit(perform_logout())

    parser = argparse.ArgumentParser(
        prog="voyager-relay",
        description="VoyagerRelay (Notion AI Terminal Asistanı & Otonom Kodlama Ajanı)",
        add_help=False
    )
    parser.add_argument("-h", "--help", action="store_true", help="Yardım mesajını gösterir")
    parser.add_argument("-m", "--model", type=str, default="auto", help="Kullanılacak model (auto [varsayılan], sonnet, opus, gpt, gemini, kimi)")
    parser.add_argument("-f", "--file", type=str, action="append", help="Bağlam olarak gönderilecek dosya(lar)")
    parser.add_argument("-P", "--prompt-file", type=str, help="İstemi bir metin dosyasından okur (büyük bağlamlar için)")
    parser.add_argument("-e", "--edit", type=str, help="Güvenli Diff önizlemeli düzenlenecek dosya")
    parser.add_argument("-y", "--yes", action="store_true", help="Diff onayını sormadan doğrudan uygular")
    parser.add_argument("-a", "--agent", action="store_true", help="Otonom Araç Döngüsünü (ReAct) başlatır")
    parser.add_argument("-s", "--save-to-notion", type=str, help="Çıktıyı Notion'da yeni bir sayfaya kaydeder")
    parser.add_argument("-t", "--think", action="store_true", help="Modelin düşünme adımlarını (reasoning) gösterir")
    parser.add_argument("-i", "--interactive", action="store_true", help="İnteraktif canlı sohbet konsolunu başlatır")
    parser.add_argument("-n", "--new", action="store_true", help="Yeni bir sohbet oturumu başlatır")
    parser.add_argument("--list-models", action="store_true", help="Kullanılabilir tüm modelleri listeler")
    parser.add_argument("--rollback", type=str, help="Belirtilen dosyayı .bak yedeğinden güvenle geri yükler")
    parser.add_argument("--queue-add", type=str, nargs=2, metavar=("BASLIK", "ACIKLAMA"), help="Görev kuyruğuna yeni iş ekler")
    parser.add_argument("--queue-list", action="store_true", help="Kuyruktaki görevleri listeler")
    parser.add_argument("--worker", action="store_true", help="Arka plan görev kuyruğu worker'ını çalıştırır")
    parser.add_argument("--debug", action="store_true", help="Detaylı sistem ve ağ loglarını gösterir")
    parser.add_argument("prompt", nargs="*", help="Notion AI'a iletilecek soru veya görev")

    args = parser.parse_args()

    if args.debug:
        import logging
        logging.getLogger("notion_opus").setLevel(logging.INFO)

    if args.help:
        print("""
Kullanım:
  voyager-relay "Sorunuz veya göreviniz"
  voyager-relay login                           (Notion hesabına giriş yap - Chrome ile otomatik)
  voyager-relay login --manual                  (Token yapıştırarak manuel giriş yap)
  voyager-relay whoami                          (Aktif Notion hesap ve bağlantı durumunu göster)
  voyager-relay logout                          (Mevcut oturumu sonlandır ve hesaptan çıkış yap)
  voyager-relay -m opus "Mimari plan çıkar"     (Model Seçimi: opus, sonnet, gpt5, kimi...)
  voyager-relay -P prompt.txt                   (Büyük istem dosyasından bağlam okur)
  voyager-relay -e app.py "Hata yakalama ekle"  (Güvenli Diff Modu)
  voyager-relay -a "Kodları otonom test et"     (Otonom Ajan Modu)
  voyager-relay -f main.py "Analiz et"          (Dosya Bağlamı)
  voyager-relay -s "Rapor" "Özet çıkar"         (Notion'a Sayfa Basma)
  voyager-relay --queue-add "İş" "Açıklama"     (Arka Plan Görev Kuyruğuna Ekleme)
  voyager-relay --queue-list                    (Kuyruktaki Görevleri Listele)
  voyager-relay --worker                        (Görev Kuyruğu Worker'ı)
  voyager-relay new                             (Oturumu Sıfırlama)
  voyager-relay --list-models                   (Desteklenen Modelleri Listele)
""")
        sys.exit(0)

    if args.list_models:
        print_models()
        sys.exit(0)

    if args.rollback:
        success, msg = rollback_patch(args.rollback, auto_approve=args.yes)
        print(f"\n{msg}")
        sys.exit(0 if success else 1)

    # Queue commands
    if args.queue_add:
        title, desc = args.queue_add
        tid = create_task(title, desc)
        print(f"\033[1;32m[Görev Kuyruğu]\033[0m ✓ Görev başarıyla kuyruğa eklendi: #{tid} - '{title}'")
        sys.exit(0)

    if args.queue_list:
        tasks = list_tasks()
        print("=" * 60)
        print("                GÖREV KUYRUĞU LİSTESİ                 ")
        print("=" * 60)
        if not tasks:
            print("(Kuyrukta henüz kayıtlı görev yok)")
        for t in tasks:
            status_color = "\033[32m" if t["status"] == "completed" else ("\033[33m" if t["status"] == "running" else "\033[36m")
            print(f" #{t['id']:<8} | {status_color}{t['status'].upper():<10}\033[0m | {t['title']}")
        print()
        sys.exit(0)

    if args.worker:
        try:
            account = get_default_account()
        except RuntimeError as e:
            print(f"\033[1;31m[Hata]\033[0m {e}")
            sys.exit(1)
        client = NotionOpusAPI(account)
        manager = ConversationManager()
        print("\033[1;35m[Kuyruk Worker]\033[0m Görev kuyruğu dinleyicisi başlatıldı. Bekleyen işler taranıyor...")
        has_task = run_worker_cycle(client, manager, auto_save_notion=True)
        if not has_task:
            print("[Kuyruk Worker] Kuyrukta bekleyen görev bulunamadı.")
        sys.exit(0)

    # Reset command
    if args.prompt and len(args.prompt) == 1 and args.prompt[0].lower() in ("new", "reset"):
        manager = ConversationManager()
        get_or_create_conversation(manager, force_new=True)
        print("--- Yeni Notion AI Oturumu Başlatıldı ---")
        sys.exit(0)

    # Gather piped input without blocking
    piped_input = ""
    if has_stdin_data():
        try:
            piped_input = sys.stdin.read().strip()
        except Exception:
            pass

    # Gather prompt from file
    prompt_file_content = ""
    if args.prompt_file:
        if os.path.exists(args.prompt_file):
            try:
                with open(args.prompt_file, "r", encoding="utf-8", errors="replace") as pf:
                    prompt_file_content = pf.read().strip()
            except Exception as e:
                print(f"[Hata] İstem dosyası okunamadı {args.prompt_file}: {e}")
                sys.exit(1)
        else:
            print(f"[Hata] İstem dosyası bulunamadı: {args.prompt_file}")
            sys.exit(1)

    # Gather attached files
    files_context = ""
    if args.file:
        for file_path in args.file:
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        f_content = f.read()
                    files_context += f"\n\n--- DOSYA: {file_path} ---\n```\n{f_content}\n```"
                except Exception as e:
                    print(f"[Uyarı] Dosya okunamadı {file_path}: {e}")
            else:
                print(f"[Uyarı] Dosya bulunamadı: {file_path}")

    user_query = " ".join(args.prompt).strip()
    if prompt_file_content:
        user_query = f"{user_query}\n\n{prompt_file_content}".strip()
    final_prompt = user_query
    if files_context:
        final_prompt = f"{final_prompt}\n\nİlişkili Dosyalar:{files_context}"
    if piped_input:
        final_prompt = f"{final_prompt}\n\nBoru (Piped) İçeriği:\n{piped_input}"

    if args.interactive or (not final_prompt and not args.edit):
        interactive_loop(args)
        sys.exit(0)

    # Pillar 2: Autonomous ReAct Agent Loop
    if args.agent:
        try:
            account = get_default_account()
        except RuntimeError as e:
            print(f"\033[1;31m[Hata]\033[0m {e}")
            sys.exit(1)
        client = NotionOpusAPI(account)
        manager = ConversationManager()
        actual_model = resolve_model(args.model)
        conv_id = get_or_create_conversation(manager, force_new=args.new)
        run_agent_loop(
            client=client,
            manager=manager,
            conv_id=conv_id,
            user_goal=final_prompt,
            model_name=actual_model,
            show_thinking=args.think
        )
        sys.exit(0)

    # Pillar 1 & Standard Execution
    ask_notion(
        prompt=final_prompt,
        model_name=args.model,
        force_new=args.new,
        show_thinking=args.think,
        edit_file=args.edit,
        save_title=args.save_to_notion,
        auto_approve=args.yes,
    )

if __name__ == "__main__":
    main()
