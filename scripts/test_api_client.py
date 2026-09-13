"""Interactive and CLI client to test EnPusula Advisor API with custom inputs."""
import argparse
import json
import sys
import httpx

API_BASE_URL = "http://127.0.0.1:8000"


def print_banner():
    print("=" * 65)
    print("EnPusula - Canlı Danışman API Test İstemcisi")
    print("AMD Radeon RX 9070 XT GPU & Google DeepMind Gemma 4 Entegrasyonu")
    print("=" * 65)


def run_test(idea: str, media_type: str, user_id: str, base_url: str = API_BASE_URL):
    print(f"\n[GÖNDERİLEN İSTEK]")
    print(f"  Kullanıcı ID : {user_id}")
    print(f"  Fikir        : {idea}")
    print(f"  Medya Türü   : {media_type}")
    print(f"  Hedef API    : {base_url}/api/recommend/advisor")

    payload = {
        "user_id": user_id,
        "idea": idea,
        "media_type": media_type,
        "horizon": "next_7_days",
    }

    # 1. Try hitting live HTTP server
    response_data = None
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(f"{base_url}/api/recommend/advisor", json=payload)
            if resp.status_code == 200:
                response_data = resp.json()
    except Exception:
        # 2. If live server is not running, fall back seamlessly to in-process FastAPI TestClient
        print("\n(Bilgi: Canlı HTTP sunucusu algılanamadı, in-process FastAPI TestClient ile test ediliyor...)")
        from fastapi.testclient import TestClient
        from backend.app import app

        with TestClient(app) as test_client:
            resp = test_client.post("/api/recommend/advisor", json=payload)
            if resp.status_code == 200:
                response_data = resp.json()
            else:
                print(f"Hata: {resp.status_code} - {resp.text}")
                return

    if not response_data:
        print("\n[HATA] API'ye bağlanılamadı ve yanıt alınamadı.")
        return

    print("\n" + "=" * 65)
    print("[API YANITI BAŞARIYLA ALINDI]")
    print("=" * 65)
    print(f"Tespit Edilen Kategori : {response_data.get('topic')}")
    print(f"Model Sürümü           : {response_data.get('model_version')}")
    print(f"Önerilen Etiketler     : {', '.join(response_data.get('suggested_tags', []))}")

    print("\n[ÖNERİLEN PAYLAŞIM PENCERELERİ (gözlemsel lift; kesin saat iddiası değildir)]")
    for i, window in enumerate(response_data.get("windows", []), 1):
        lift = window.get("observational_time_lift", 0.0)
        print(
            f"  {i}. {window.get('weekday')} {window.get('time_range_local')} "
            f"(yerel başlangıç {window.get('window_start_local', '')[:16]}) | "
            f"gözlemsel lift {lift:+.2f} | destek: {window.get('support_post_count')} | "
            f"güven: {window.get('confidence_label')} | kanıt: {window.get('evidence_level')}"
        )
    if response_data.get("is_tie_or_broad_window"):
        print("  Not: kanıt kesin sıralama için yeterli değil; pencere seçenekleri sunuldu.")

    similar = response_data.get("similar_posts", [])
    print(f"\n[QDRANT'TAN GETİRİLEN BENZER GÖNDERİLER ({len(similar)} adet)]")
    for p in similar[:3]:
        print(f"  - [{p.get('popularity_score', 0):.1f} puan] {p.get('title', '')[:55]}...")

    print("\n[GEMMA 4 STRATEJİK DANIŞMANLIK TAVSİYESİ]")
    print(f"  \"{response_data.get('explanation')}\"")
    print("=" * 65)


def main():
    print_banner()
    parser = argparse.ArgumentParser(description="EnPusula API Test İstemcisi")
    parser.add_argument("--idea", type=str, help="İçerik fikri metni")
    parser.add_argument("--media", choices=["photo", "video"], default="photo", help="Medya türü (photo/video)")
    parser.add_argument("--user", type=str, default="alpeerkaraca", help="Kullanıcı adı")
    parser.add_argument("--url", type=str, default=API_BASE_URL, help="FastAPI Base URL")

    args = parser.parse_args()

    idea = args.idea
    media_type = args.media
    user_id = args.user

    # If idea is not provided via CLI flag, prompt interactively
    if not idea:
        print("\nİnteraktif Mod: Lütfen test etmek istediğiniz bilgileri girin:")
        try:
            input_idea = input("1. İçerik Fikriniz (Örn: 'Python ile yapay zeka ajanları mimarisi'): ").strip()
            if input_idea:
                idea = input_idea
            else:
                idea = "Yapay Zeka ve Derin Öğrenme ile Doğal Dil İşleme Mimarileri"

            input_media = input("2. Medya Formatı (1: photo, 2: video) [Varsayılan: photo]: ").strip()
            if input_media == "2" or input_media.lower() == "video":
                media_type = "video"
            else:
                media_type = "photo"

            input_user = input(f"3. Kullanıcı ID [Varsayılan: {user_id}]: ").strip()
            if input_user:
                user_id = input_user
        except (KeyboardInterrupt, EOFError):
            print("\nÇıkış yapıldı.")
            sys.exit(0)

    run_test(idea=idea, media_type=media_type, user_id=user_id, base_url=args.url)


if __name__ == "__main__":
    main()
