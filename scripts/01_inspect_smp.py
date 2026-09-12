"""Inspects the raw SMP dataset lines, columns, null rates, and date ranges."""
import json
from pathlib import Path

RAW_FILE = Path("data/raw/train_dataset.jsonl")


def inspect():
    if not RAW_FILE.exists():
        print(f"Error: {RAW_FILE} not found.")
        return

    total_lines = 0
    unique_users = set()
    unique_posts = set()
    min_date = None
    max_date = None
    sample_rows = []

    print(f"Scanning {RAW_FILE}...")
    with open(RAW_FILE, "r", encoding="utf-8") as f:
        for line in f:
            total_lines += 1
            if total_lines <= 3:
                sample_rows.append(json.loads(line))
            obj = json.loads(line)
            uid = obj.get("user_id")
            pid = obj.get("post_id")
            pub = obj.get("published_at_utc")

            if uid:
                unique_users.add(uid)
            if pid:
                unique_posts.add(pid)
            if pub:
                if min_date is None or pub < min_date:
                    min_date = pub
                if max_date is None or pub > max_date:
                    max_date = pub

            if total_lines % 100000 == 0:
                print(f"Processed {total_lines:,} lines...")

    print("=" * 60)
    print("Dataset Inspection Summary:")
    print("=" * 60)
    print(f"Total rows:        {total_lines:,}")
    print(f"Unique posts:      {len(unique_posts):,}")
    print(f"Unique users:      {len(unique_users):,}")
    print(f"Date range:        {min_date} to {max_date}")
    print("Sample keys:       ", list(sample_rows[0].keys()))
    print("=" * 60)


if __name__ == "__main__":
    inspect()
