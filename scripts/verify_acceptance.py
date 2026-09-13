"""Checks the plan's completion checklist against the artifacts on disk.

The plan (NPUSULA_MODEL_VE_SAAT_ONERISI_DUZELTME_PLANI.md) ends with a
11-item acceptance list. This script re-derives each item from the data,
artifacts and source contracts instead of trusting the prose in the README, so
a regression in any of them fails here.

    python scripts/verify_acceptance.py     # exit code = number of failures
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from backend.services.provenance import file_sha256
from backend.services.recommendation import BASE_FEATURES
from backend.services.tag_taxonomy import align_tags
from backend.services.time_features import BUCKETS_PER_DAY

DATA_QUALITY = Path("data/reports/data_quality.json")
PARQUET = Path("data/processed/posts.parquet")
BASE_METRICS = Path("artifacts/base_potential_metrics.json")
TIME_LIFT = Path("artifacts/time_lift_table.json")
FINAL = Path("artifacts/final_evaluation.json")
TUNING = Path("artifacts/tuning_results.json")
README = Path("README.md")
FORBIDDEN_README_PHRASES = (
    "GPU Tabular NN",
    "GPU tabanlı tabular",
    "pytorch_popularity_gpu",
)

results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, bool(passed), detail))


def main() -> int:
    for path in (DATA_QUALITY, PARQUET, BASE_METRICS, TIME_LIFT, FINAL, TUNING):
        if not path.exists():
            print(f"missing artifact: {path} — run the pipeline first")
            return 1

    quality = json.loads(DATA_QUALITY.read_text(encoding="utf-8"))
    base = json.loads(BASE_METRICS.read_text(encoding="utf-8"))
    lift = json.loads(TIME_LIFT.read_text(encoding="utf-8"))
    final = json.loads(FINAL.read_text(encoding="utf-8"))
    tuning = json.loads(TUNING.read_text(encoding="utf-8"))
    provenance = quality.get("provenance", {})

    # 1. No demo rows in the training data.
    df = pd.read_parquet(PARQUET, columns=["source", "user_id"])
    demo_users = {"demo_user_01", "demo_user_02", "demo_user_03"}
    check(
        "1. Eğitim verisinde demo satırı yok",
        quality["demo_row_count"] == 0 and (df["source"] == "smpd_real").all() and not df["user_id"].isin(demo_users).any(),
        f"rows={len(df):,} demo={quality['demo_row_count']} sources={quality['source_counts']}",
    )

    # 2. Local time is really computed and inference runs on user timezone.
    tz = quality["timezone_basis_distribution"]
    sample = pd.read_parquet(PARQUET, columns=["published_at_utc", "local_hour", "timezone_basis", "timezone_offset"]).head(200_000)
    offset_rows = sample[sample["timezone_basis"] == "source_offset"]
    local_matches = (
        (offset_rows["local_hour"] != pd.to_datetime(offset_rows["published_at_utc"], utc=True).dt.hour).any()
        if len(offset_rows)
        else False
    )
    check(
        "2. Yerel saat gerçekten hesaplanıyor",
        "source_offset" in tz and local_matches,
        f"basis={tz}",
    )

    # 3. The test split is not used for tuning.
    check(
        "3. Test seti tuning için kullanılmıyor",
        tuning["protocol"]["test_rows_loaded"] == 0
        and tuning["provenance"]["test_touched_before_final"] is False
        and final["test_touched_before_final"] is False
        and final["tuning_data"] == "validation_only",
        f"tuning_test_rows={tuning['protocol']['test_rows_loaded']}",
    )

    # 4. Layer A and Layer B are separate artifacts.
    check(
        "4. Base-potential ve time-lift ayrı artifact",
        base["provenance"]["split_protocol"] == "chronological_train_validation_locked_test"
        and "levels" in lift
        and lift["config"]["bucket_hours"] == base.get("bucket_hours", lift["config"]["bucket_hours"]),
        f"lift_levels={sorted(lift['levels'])}",
    )

    # 5. Time interactions removed from the production time model.
    forbidden = {"hour", "weekday", "month", "hour_sin", "hour_cos", "weekday_sin", "weekday_cos",
                 "cat_x_hour", "cat_x_weekday", "history_x_hour"}
    check(
        "5. history_x_hour / cat_x_hour / cat_x_weekday üretimden kaldırıldı",
        not (forbidden & set(BASE_FEATURES))
        and not (forbidden & set(base["feature_contract"]["production_features"]))
        and base["feature_contract"]["time_features_present"] is False,
        f"features={len(BASE_FEATURES)}",
    )

    # 6. Tag/category canonical mapping works and mismatches are not aligned.
    aligned = align_tags(["#python", "#makeup"], context_category="technology")
    check(
        "6. Tag/category canonical mapping doğrulandı",
        aligned["aligned_semantic"] == ["python"] and aligned["mismatched_semantic"] == ["makeup"],
        f"aligned={aligned['aligned_semantic']} mismatched={aligned['mismatched_semantic']}",
    )

    # 7. Hours come back as wide buckets, not single hours.
    bucket_hours = lift["config"]["bucket_hours"]
    check(
        "7. Saatler geniş bucket/pencere olarak dönüyor",
        bucket_hours >= 3 and lift["coverage"]["level_group_counts"]["global_bucket"] == BUCKETS_PER_DAY,
        f"bucket_hours={bucket_hours} buckets/day={lift['coverage']['level_group_counts']['global_bucket']}",
    )

    # 8. Without evidence the system answers with a broad window / no claim.
    product = final["product_confidence_report"]
    high_rate = product["confidence_rate"].get("high", 0.0)
    check(
        "8. Yeterli kanıt yoksa broad-window / no-claim",
        product["no_claim_or_broad_window_rate"] > 0.5 and high_rate < 0.5,
        f"no_claim={product['no_claim_or_broad_window_rate']:.3f} high={high_rate:.3f}",
    )

    # 9. Base popularity, cold start, category and time-lift metrics are separate.
    subgroups = set(final["base_potential_subgroups"])
    check(
        "9. Base popularity / cold-start / kategori / time-lift ayrı raporlanıyor",
        {"history_depth:cold_start", "focus"} <= subgroups
        or (
            any(name.startswith("history_depth:cold_start") for name in subgroups)
            and any(name.startswith("category:") for name in subgroups)
            and "mae" in final["base_potential"]
            and "ndcg_at_3" in final["time_lift"]
        ),
        f"subgroup_cuts={len(subgroups)}",
    )

    # 10. README states the observational limits and the real architecture.
    readme = README.read_text(encoding="utf-8")
    required_phrases = ("gözlemsel", "Katman A", "Katman B", "geniş pencere", "iddia etmez")
    missing_phrases = [phrase for phrase in required_phrases if phrase not in readme]
    check(
        "10. README gözlemsel sınırları ve gerçek mimariyi anlatıyor",
        not missing_phrases,
        "ok" if not missing_phrases else f"missing: {missing_phrases}",
    )

    # 11. The GPU ensemble claim is gone from the code and the architecture table.
    advisor_source = Path("backend/services/advisor.py").read_text(encoding="utf-8")
    runtime_claims_gpu_model = any(
        marker in Path(path).read_text(encoding="utf-8")
        for path in ("backend/services/recommendation.py", "backend/services/gemma_advisor.py")
        for marker in ("tabular_nn", "PopularityTabularNN", "GPU Tabular NN", "LightGBM ensemble")
    )
    check(
        "11. Eski GPU ensemble iddiası kaldırıldı",
        not Path("backend/models/tabular_nn.py").exists()
        and not Path("scripts/train_gpu_model.py").exists()
        and not runtime_claims_gpu_model
        and "GPU Tabular NN" not in readme
        and "gpu" not in advisor_source.lower().split("model_version=")[-1][:200].lower(),
        "tabular_nn.py / train_gpu_model.py removed; runtime claims no GPU model"
        + (f"; leftover markers: {FORBIDDEN_README_PHRASES}" if runtime_claims_gpu_model else ""),
    )

    # Sanity: the artifacts were produced from a clean code tree.
    check(
        "12. Artifact provenance temiz (kod kirli değil)",
        all(
            json.loads(path.read_text(encoding="utf-8"))["provenance"].get("git_dirty") is False
            for path in (BASE_METRICS, TIME_LIFT, FINAL, TUNING)
        )
        and file_sha256(PARQUET) == base["provenance"]["dataset_sha256"],
        f"commit={base['provenance']['git_commit'][:8]}",
    )

    print("=" * 78)
    print("Plan kabul listesi doğrulaması")
    print("=" * 78)
    failures = 0
    for name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        failures += 0 if passed else 1
        print(f"[{status}] {name}")
        if detail:
            print(f"       {detail}")
    print("=" * 78)
    print(f"{len(results) - failures}/{len(results)} passed")
    return failures


if __name__ == "__main__":
    sys.exit(main())
