import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import get_default_account
from app.conversation import ConversationManager
from app.notion_client import NotionOpusAPI


def main():
    try:
        account = get_default_account()
    except ValueError as e:
        print(f"[Yapilandirma Hatasi] {e}")
        sys.exit(1)

    client = NotionOpusAPI(account)
    manager = ConversationManager()

    print("=" * 45)
    print("           Notion AI Terminal            ")
    print(" Çıkmak için 'exit', yeni sohbet için 'new'")
    print("=" * 45)

    current_conv = manager.new_conversation()

    while True:
        try:
            user_input = input("\n[Sen]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nÇıkılıyor...")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "q"):
            print("Çıkılıyor...")
            break

        if user_input.lower() in ("new", "reset", "cls"):
            current_conv = manager.new_conversation()
            print("\n--- Yeni Sohbet Başlatıldı ---")
            continue

        transcript = manager.get_transcript(client, current_conv, user_input, "claude-opus4.6")

        print("\n[Notion AI]: ", end="", flush=True)

        full_text = ""
        stream = client.stream_response(transcript)

        try:
            for item in stream:
                if isinstance(item, dict):
                    item_type = item.get("type")
                    if item_type == "content":
                        text = str(item.get("text", "") or "")
                        if text:
                            print(text, end="", flush=True)
                            full_text += text
                    elif item_type == "search":
                        search_data = item.get("data", {})
                        if isinstance(search_data, dict) and search_data.get("queries"):
                            print(f"\n[Arama: {', '.join(search_data.get('queries', []))}]\n", end="", flush=True)
                    continue

                if isinstance(item, str) and item:
                    print(item, end="", flush=True)
                    full_text += item
        except KeyboardInterrupt:
            print("\n[Uyarı] Kullanıcı çıktıyı durdurdu")
        except Exception as e:
            print(f"\n[Hata] Akış okuma hatası: {e}")

        print()

        if full_text:
            manager.persist_round(current_conv, user_input, full_text)


if __name__ == "__main__":
    main()
