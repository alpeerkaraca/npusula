"""Smoke test verifying all core NPusula workflows end-to-end."""
import json
from fastapi.testclient import TestClient

from backend.app import app


def run_smoke_test():
    print("=" * 60)
    print("NPusula MVP - End-to-End Smoke Test")
    print("=" * 60)

    with TestClient(app) as client:
        # 1. Health check
        health = client.get("/api/health").json()
        print(f"[1/6] Health check: {health}")
        assert health["status"] == "ok"

        # 2. Registered accounts (synthetic demo fixtures were removed)
        users = client.get("/api/demo-users").json()
        print(f"[2/6] Registered accounts: {len(users)}")

        # 3. Quick recommendation for a real user with posting history
        quick = client.get(
            "/api/recommend/quick/31253@N15", params={"timezone": "Europe/Istanbul"}
        ).json()
        print(f"[3/6] Quick recommendation for 31253@N15 (real SMPD user):")
        print(f"      Active topic: {quick['active_topic']}")
        print(f"      Confidence: {quick['confidence_label']} | timezone basis: {quick['timezone_basis']}")
        for window in quick["windows"]:
            print(
                f"      - {window['weekday']} {window['time_range_local']} "
                f"(local {window['window_start_local'][:16]}) | lift {window['observational_time_lift']:+.3f} "
                f"| kanıt: {window['evidence_level']} | destek: {window['support_post_count']}"
            )
        print(f"      Explanation: {quick['explanation']}")

        # 4. Profile drift check for a real user concentrated in one topic
        profile = client.get("/api/profile/36743@N91").json()
        print(f"[4/6] Profile drift check for 36743@N91 (real SMPD user):")
        print(f"      Declared: {profile['declared_topics']}")
        print(f"      Behavioral top: {profile['behavioral_topics'][0]['topic']} ({profile['behavioral_topics'][0]['weight']})")
        print(f"      Drift detected: {profile['drift_detected']}")
        print(f"      Question: {profile['question']}")
        assert profile["drift_detected"] is True

        # 5. User accepts drift update
        decision = client.post("/api/profile/36743@N91/decision", json={"accept": True}).json()
        print(f"[5/6] Decision accepted. Updated active recommendation topics:")
        for t in decision["active_recommendation_topics"][:3]:
            print(f"      - {t['topic']}: {t['weight']}")
        assert decision["active_recommendation_topics"][0]["topic"] == profile["behavioral_topics"][0]["topic"]

        # 6. Advisor query
        idea_payload = {
            "user_id": "31253@N15",
            "idea": "Büyük dil modellerinde prompt mühendisliği ve dikkat mekanizmaları",
            "media_type": "photo",
            "horizon": "next_7_days",
            "timezone": "Europe/Istanbul",
        }
        advisor = client.post("/api/recommend/advisor", json=idea_payload).json()
        print(f"[6/6] Advisor Response for idea: '{idea_payload['idea'][:40]}...'")
        print(f"      Inferred Topic: {advisor['topic']}")
        print(f"      Base potential: {advisor['windows'][0]['base_potential'] if advisor['windows'] else '-'}"
              f" | Confidence: {advisor['confidence_level']} | tie/no-claim: {advisor['is_tie_or_broad_window']}")
        print(f"      Recommended Windows:")
        for window in advisor["windows"]:
            print(
                f"      - {window['weekday']} {window['time_range_local']} "
                f"| lift {window['observational_time_lift']:+.3f} | {window['evidence_level']}"
            )
        print(f"      Suggested Tags: {advisor['suggested_tags']}")
        print(f"      Similar Posts Count: {len(advisor['similar_posts'])}")
        print(f"      Explanation: {advisor['explanation']}")

    print("=" * 60)
    print("ALL SMOKE TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    run_smoke_test()
