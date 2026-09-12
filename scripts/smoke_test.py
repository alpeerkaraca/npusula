"""Smoke test verifying all core EnPusula workflows end-to-end."""
import json
from fastapi.testclient import TestClient

from backend.app import app


def run_smoke_test():
    print("=" * 60)
    print("EnPusula MVP - End-to-End Smoke Test")
    print("=" * 60)

    with TestClient(app) as client:
        # 1. Health check
        health = client.get("/api/health").json()
        print(f"[1/6] Health check: {health}")
        assert health["status"] == "ok"

        # 2. Demo users
        users = client.get("/api/demo-users").json()
        print(f"[2/6] Demo users loaded: {[u['user_id'] for u in users]}")
        assert len(users) == 3

        # 3. Quick recommendation for aligned user
        quick = client.get("/api/recommend/quick/demo_user_01").json()
        print(f"[3/6] Quick recommendation for demo_user_01 (aligned):")
        print(f"      Active topic: {quick['active_topic']}")
        for s in quick["slots"]:
            print(f"      - {s['datetime_utc'][:16]} | {s['predicted_popularity']} | {s['label']}")
        print(f"      Explanation: {quick['explanation']}")

        # 4. Profile drift check for drift user
        profile = client.get("/api/profile/demo_user_02").json()
        print(f"[4/6] Profile drift check for demo_user_02 (drift):")
        print(f"      Declared: {profile['declared_topics']}")
        print(f"      Behavioral top: {profile['behavioral_topics'][0]['topic']} ({profile['behavioral_topics'][0]['weight']})")
        print(f"      Drift detected: {profile['drift_detected']}")
        print(f"      Question: {profile['question']}")
        assert profile["drift_detected"] is True

        # 5. User accepts drift update
        decision = client.post("/api/profile/demo_user_02/decision", json={"accept": True}).json()
        print(f"[5/6] Decision accepted. Updated active recommendation topics:")
        for t in decision["active_recommendation_topics"][:3]:
            print(f"      - {t['topic']}: {t['weight']}")
        assert decision["active_recommendation_topics"][0]["topic"] == profile["behavioral_topics"][0]["topic"]

        # 6. Advisor query
        idea_payload = {
            "user_id": "demo_user_01",
            "idea": "Büyük dil modellerinde prompt mühendisliği ve dikkat mekanizmaları",
            "media_type": "photo",
            "horizon": "next_7_days",
        }
        advisor = client.post("/api/recommend/advisor", json=idea_payload).json()
        print(f"[6/6] Advisor Response for idea: '{idea_payload['idea'][:40]}...'")
        print(f"      Inferred Topic: {advisor['topic']}")
        print(f"      Recommended Slots:")
        for s in advisor["recommendations"]:
            print(f"      - {s['datetime_utc'][:16]} | Score: {s['predicted_popularity']} | {s['label']}")
        print(f"      Suggested Tags: {advisor['suggested_tags']}")
        print(f"      Similar Posts Count: {len(advisor['similar_posts'])}")
        print(f"      Explanation: {advisor['explanation']}")

    print("=" * 60)
    print("ALL SMOKE TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    run_smoke_test()
