"""Normalizes raw SMPD dataset to canonical PostRecord format in Parquet."""
from datetime import datetime, timezone
import json
from pathlib import Path
import numpy as np
import pandas as pd

from backend.config import settings
from backend.services.history_feature import compute_leakage_free_history

RAW_FILE = Path("data/raw/train_dataset.jsonl")
OUTPUT_PARQUET = Path("data/processed/posts.parquet")
REPORT_PATH = Path("data/reports/data_quality.json")
REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)


def normalize_dataset():
    print(f"Reading raw records from {RAW_FILE}...")

    records = []
    skipped = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    with open(RAW_FILE, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            obj = json.loads(line)
            target_pop = obj.get("target_popularity")
            if target_pop is None:
                skipped += 1
                continue

            try:
                pop_score = float(target_pop)
                if not np.isfinite(pop_score):
                    skipped += 1
                    continue
            except (ValueError, TypeError):
                skipped += 1
                continue

            pid = str(obj.get("post_id", ""))
            uid = str(obj.get("user_id", ""))
            if not pid or not uid:
                skipped += 1
                continue

            title = str(obj.get("text") or "").strip()
            raw_tags = obj.get("tags") or []
            tags = [f"#{str(t).lower().replace(' ', '')}" for t in raw_tags if str(t).strip()]
            cat1 = str(obj.get("source_category_l1") or "").strip() or None
            cat2 = str(obj.get("source_category_l2") or "").strip() or None
            concept = str(obj.get("source_concept") or "").strip() or None
            media_type = str(obj.get("media_type") or "photo").lower()
            if media_type not in ["photo", "video"]:
                media_type = "photo"

            pub_dt = str(obj.get("published_at_utc", ""))
            user_photos = obj.get("source_user_photo_count")
            
            tz_offset = obj.get("timezone_offset")
            if tz_offset is not None:
                time_basis = "local"
            else:
                time_basis = "utc_fallback"

            records.append({
                "schema_version": "1.0",
                "source": "smpd_real",
                "post_id": pid,
                "user_id": uid,
                "published_at_utc": pub_dt,
                "timezone_offset": tz_offset,
                "time_basis": time_basis,
                "title": title,
                "description": None,
                "tags": tags,
                "media_type": media_type,
                "media_path": obj.get("media_ref"),
                "media_available": True if obj.get("source_media_status") == "ready" else False,
                "category_l1": cat1,
                "category_l2": cat2,
                "concept": concept,
                "latitude": obj.get("source_latitude"),
                "longitude": obj.get("source_longitude"),
                "source_user_photo_count": user_photos,
                "popularity_score": round(pop_score, 2),
                "ingested_at_utc": now_iso,
            })

            if (idx + 1) % 100000 == 0:
                print(f"Processed {idx + 1:,} rows...")

    print(f"Read {len(records):,} valid records (skipped {skipped:,}).")
    df = pd.DataFrame(records)

    # Add demo accounts posts to ensure end-to-end demo consistency
    demo_path = Path("artifacts/demo_accounts.json")
    if OUTPUT_PARQUET.exists():
        existing_df = pd.read_parquet(OUTPUT_PARQUET)
        demo_posts = existing_df[existing_df["user_id"].isin(["demo_user_01", "demo_user_02", "demo_user_03"])]
        if not demo_posts.empty:
            print(f"Merging {len(demo_posts)} demo fixture posts...")
            demo_posts = demo_posts[[c for c in demo_posts.columns if c in df.columns]]
            df = pd.concat([df, demo_posts], ignore_index=True)

    print("Computing leakage-free chronological user history priors...")
    df = compute_leakage_free_history(df, default_popularity_mean=5.5)

    # Save to Parquet
    print(f"Saving {len(df):,} records to {OUTPUT_PARQUET}...")
    OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_PARQUET, index=False)

    # Data quality report
    quality_report = {
        "total_posts": int(len(df)),
        "unique_posts": int(df["post_id"].nunique()),
        "unique_users": int(df["user_id"].nunique()),
        "skipped_invalid_rows": int(skipped),
        "mean_popularity": round(float(df["popularity_score"].mean()), 3),
        "std_popularity": round(float(df["popularity_score"].std()), 3),
        "min_popularity": round(float(df["popularity_score"].min()), 3),
        "max_popularity": round(float(df["popularity_score"].max()), 3),
        "media_type_distribution": df["media_type"].value_counts().to_dict(),
        "date_range": [str(df["published_at_utc"].min()), str(df["published_at_utc"].max())],
        "null_percentages": {col: round(float(df[col].isna().mean() * 100), 2) for col in df.columns},
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(quality_report, f, indent=2)

    print("=" * 60)
    print(f"Normalization Complete!")
    print(f"Total processed posts: {quality_report['total_posts']:,}")
    print(f"Mean popularity score: {quality_report['mean_popularity']}")
    print(f"Report saved to:       {REPORT_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    normalize_dataset()
