"""Runnable idea battery for the advisor API.

Sends a fixed set of content ideas (topic coverage, edge cases, guardrail
rejections) plus user-scenario checks to a running server and verifies the
response contract. Exit code = number of failures, so it can gate a demo.

Usage:
    uvicorn backend.app:app --port 8000        # port 8081-8280 is reserved on this machine
    python scripts/idea_battery.py --base-url http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import sys

import httpx

TOPICS = {
    "Yapay Zeka", "Yazılım", "Teknoloji Trendleri", "Oyun", "Eğitim",
    "Finans", "Spor", "Kültür-Sanat", "Girişimcilik", "Yaşam",
}
CATEGORIES = {
    "technology", "automotive", "fashion_beauty", "travel_tourism",
    "food_dining", "entertainment_gaming", "sports_fitness",
    "nature_wildlife", "art_design", "business_economy", "social_lifestyle",
}

# Ideas with exact expectations (verified behavior) and structural checks.
BATTERY: list[dict] = [
    # --- Exact expectations (regression anchors) ---
    {"idea": "Ailemle geçirdiğim mutlu bir haftasonu", "media": "video",
     "topic": "Yaşam", "category": "social_lifestyle",
     "tag_any": ["#yaşam", "#lifestyle", "#günlükyaşam"]},
    {"idea": "amerikan güreşi izledik", "media": "video",
     "topic": "Spor", "category": "sports_fitness", "tag_any": ["#spor"]},
    {"idea": "Yeni nesil üretken yapay zeka modelleri ve kullanım alanları", "media": "photo",
     "topic": "Yapay Zeka", "category": "technology"},
    {"idea": "sabah kahvesi ve kitap keyfi", "media": "photo", "topic": "Eğitim"},
    # --- Topic coverage (structural + category anchors where deterministic) ---
    {"idea": "Python ile web uygulaması geliştirme ipuçları", "media": "photo", "category": "technology"},
    {"idea": "5G teknolojisi ve akıllı telefonlar", "media": "photo"},
    {"idea": "Yeni çıkan oyunlar ve espor turnuvası", "media": "video"},
    {"idea": "Üniversite sınavına hazırlık stratejileri", "media": "photo"},
    {"idea": "Borsa ve kripto yatırım stratejileri", "media": "photo", "category": "business_economy"},
    {"idea": "Sabah koşusu ve maraton antrenmanı", "media": "video", "category": "sports_fitness"},
    {"idea": "Modern sanat sergisi ve fotoğrafçılık", "media": "photo", "category": "art_design"},
    {"idea": "Startup kurarken yatırımcı bulma taktikleri", "media": "photo"},
    {"idea": "3D yazıcı ile evde üretim", "media": "photo"},
    {"idea": "100 TL altı hediye fikirleri", "media": "photo"},
    # --- English (retrieval path) ---
    {"idea": "sunset photography at the beach", "media": "photo"},
    # --- Guardrail (must be rejected with HTTP 400) ---
    {"idea": "porno video izle", "media": "video", "guardrail": True},
    {"idea": "c1pl4q ve c!ns3l video", "media": "video", "guardrail": True},
    {"idea": "bahis sitesi güvenilir giriş", "media": "video", "guardrail": True},
]

USER_CHECKS: list[tuple[str, str, dict]] = [
    ("quick warm user", "/api/recommend/quick/31253@N15", {"cold_start": False}),
    ("quick cold user", "/api/recommend/quick/cold_start_user", {"cold_start": True}),
    ("profile drift", "/api/profile/36743@N91", {"drift_detected": True}),
    ("profile no-drift", "/api/profile/60519@N0", {"drift_detected": False}),
]

DEFAULT_USER = "31253@N15"


def check_advisor(client: httpx.Client, base: str, case: dict) -> tuple[bool, str]:
    payload = {"user_id": DEFAULT_USER, "idea": case["idea"],
               "media_type": case["media"], "horizon": "next_7_days"}
    r = client.post(f"{base}/api/recommend/advisor", json=payload)

    if case.get("guardrail"):
        ok = r.status_code == 400
        detail = r.json().get("detail", "")[:40] if ok else r.text[:60]
        return ok, f"status={r.status_code} {detail}"

    if r.status_code != 200:
        return False, f"status={r.status_code} body={r.text[:80]}"
    d = r.json()
    problems = []
    if d.get("topic") not in TOPICS:
        problems.append(f"topic={d.get('topic')!r}")
    if d.get("primary_category") not in CATEGORIES:
        problems.append(f"cat={d.get('primary_category')!r}")
    if len(d.get("recommendations", [])) != 3:
        problems.append(f"slots={len(d.get('recommendations', []))}")
    if not d.get("explanation"):
        problems.append("no explanation")
    if case.get("topic") and d.get("topic") != case["topic"]:
        problems.append(f"topic={d.get('topic')} (expected {case['topic']})")
    if case.get("category") and d.get("primary_category") != case["category"]:
        problems.append(f"cat={d.get('primary_category')} (expected {case['category']})")
    if case.get("tag_any") and not set(case["tag_any"]) & set(d.get("accepted_tags", [])):
        problems.append(f"tags={d.get('accepted_tags')} (expected any of {case['tag_any']})")

    info = (f"topic={d.get('topic')} cat={d.get('primary_category')} "
            f"tags={','.join(d.get('accepted_tags', [])) or '-'} sim={len(d.get('similar_posts', []))}")
    return not problems, (info if not problems else "; ".join(problems) + " | " + info)


def check_user(client: httpx.Client, base: str, name: str, path: str, expected: dict) -> tuple[bool, str]:
    r = client.get(f"{base}{path}")
    if r.status_code != 200:
        return False, f"status={r.status_code}"
    d = r.json()
    problems = []
    for key, value in expected.items():
        if d.get(key) != value:
            problems.append(f"{key}={d.get(key)} (expected {value})")
    if "quick" in path and len(d.get("slots", [])) != 3:
        problems.append(f"slots={len(d.get('slots', []))}")
    info = f"{name}: " + ", ".join(f"{k}={d.get(k)}" for k in expected)
    return not problems, (info if not problems else "; ".join(problems))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    client = httpx.Client(timeout=args.timeout)
    try:
        client.get(f"{base}/api/health")
    except Exception as e:
        print(f"Server not reachable at {base}: {e}")
        print("Start it first:  uvicorn backend.app:app --port 8000")
        sys.exit(2)

    failures = 0
    print(f"=== Advisor idea battery ({base}) ===")
    for case in BATTERY:
        ok, info = check_advisor(client, base, case)
        failures += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] {case['idea'][:44]!r:48s} {info}")

    print("\n=== User scenarios ===")
    for name, path, expected in USER_CHECKS:
        ok, info = check_user(client, base, name, path, expected)
        failures += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] {info}")

    total = len(BATTERY) + len(USER_CHECKS)
    print(f"\nSummary: {total - failures}/{total} passed")
    sys.exit(failures)


if __name__ == "__main__":
    main()
