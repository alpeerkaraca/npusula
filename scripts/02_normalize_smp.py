"""Normalizes raw SMPD dataset to canonical PostRecord format in Parquet.

Guarantees enforced here (plan §1.1, §1.2, §1.3):

1. Only real SMPD rows from `data/raw/train_dataset.jsonl` are written. The
   previous output is never read back, so removed demo fixtures cannot be
   re-injected by a later run, and the run fails loudly if any demo user or any
   non-`smpd_real` source row ever appears.
2. Local time is derived from the post's own UTC timestamp plus the source
   timezone offset (`local_datetime`/`local_hour`/`local_weekday`). Rows without
   an offset are labelled `utc_fallback` instead of being presented as local.
3. `media_available` is only True when the referenced file is actually readable
   from disk — the source status flag alone is not accepted.
4. Unknown media types stay `unknown` (never coerced to `photo`).
5. Output columns are validated against the `PostRecord` schema (sample rows via
   the model + a full column-set check).

Outputs: `data/processed/posts.parquet`, `data/reports/data_quality.json`.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

import numpy as np
import pandas as pd

from backend.schemas.post import OPTIONAL_UNWRITTEN_FIELDS, PostRecord
from pydantic import StrictInt
from backend.services.history_feature import compute_leakage_free_history
from backend.services.provenance import file_sha256, git_commit_sha, utc_now_iso, write_json_with_provenance
from backend.services.time_features import resolve_post_local_time

RAW_FILE = Path("data/raw/train_dataset.jsonl")
OUTPUT_PARQUET = Path("data/processed/posts.parquet")
REPORT_PATH = Path("data/reports/data_quality.json")

# Media files referenced by the JSONL are resolved against this root. They are
# NOT shipped with the corpus, so `media_available` is legitimately False for
# every row today; the check exists so that a corpus which does ship them is
# reported truthfully.
MEDIA_ROOT = Path(os.getenv("SMPD_MEDIA_ROOT", "data/raw/media"))

SOURCE_ID = "smpd_real"
DEMO_USER_IDS = frozenset({"demo_user_01", "demo_user_02", "demo_user_03"})

# Deterministic sample size for full-model validation of individual rows.
SCHEMA_SAMPLE_SIZE = 500

# Columns written by this script, in output order. Kept as an explicit list so
# the schema alignment check is a real check and not a tautology.
OUTPUT_COLUMNS = [
    "schema_version",
    "source",
    "post_id",
    "user_id",
    "published_at_utc",
    "timezone_offset",
    "timezone_id",
    "local_datetime",
    "local_hour",
    "local_weekday",
    "timezone_basis",
    "title",
    "description",
    "tags",
    "media_type",
    "media_path",
    "media_available",
    "category_l1",
    "category_l2",
    "concept",
    "latitude",
    "longitude",
    "source_user_photo_count",
    "popularity_score",
    "ingested_at_utc",
    "user_post_count_prior",
    "user_popularity_mean_prior",
]


def media_file_is_readable(media_ref: str | None, media_root: Path = MEDIA_ROOT) -> bool:
    """True only when the referenced media file exists and can be opened."""
    if not media_ref:
        return False
    candidate = Path(media_ref)
    if not candidate.is_absolute():
        candidate = media_root / candidate
    try:
        with open(candidate, "rb") as handle:
            handle.read(1)
        return True
    except OSError:
        return False


def normalize_record(obj: dict, ingested_at_utc: datetime) -> dict | None:
    """Converts one raw JSONL object into a canonical row, or None if invalid."""
    target_pop = obj.get("target_popularity")
    if target_pop is None:
        return None
    try:
        pop_score = float(target_pop)
    except (ValueError, TypeError):
        return None
    if not np.isfinite(pop_score):
        return None

    post_id = str(obj.get("post_id", "") or "").strip()
    user_id = str(obj.get("user_id", "") or "").strip()
    if not post_id or not user_id:
        return None

    published_at = obj.get("published_at_utc")
    if not published_at:
        return None

    title = str(obj.get("text") or "").strip()
    raw_tags = obj.get("tags") or []
    tags = [f"#{str(tag).lower().replace(' ', '')}" for tag in raw_tags if str(tag).strip()]

    category_l1 = str(obj.get("source_category_l1") or "").strip() or None
    category_l2 = str(obj.get("source_category_l2") or "").strip() or None
    concept = str(obj.get("source_concept") or "").strip() or None

    # Unknown media types are preserved as `unknown`: coercing them to `photo`
    # would silently invent media information the source never provided.
    raw_media_type = str(obj.get("media_type") or "").strip().lower()
    media_type = raw_media_type if raw_media_type in {"photo", "video"} else "unknown"

    timezone_offset = obj.get("timezone_offset")
    timezone_id = obj.get("source_timezone_id")
    local = resolve_post_local_time(published_at, timezone_offset)
    media_ref = obj.get("media_ref")

    return {
        "schema_version": "1.0",
        "source": SOURCE_ID,
        "post_id": post_id,
        "user_id": user_id,
        "published_at_utc": local.utc_dt,
        "timezone_offset": (str(timezone_offset).strip() or None) if timezone_offset is not None else None,
        "timezone_id": (str(timezone_id).strip() or None) if timezone_id is not None else None,
        "local_datetime": local.local_dt.replace(tzinfo=None),
        "local_hour": local.local_hour,
        "local_weekday": local.local_weekday,
        "timezone_basis": local.basis,
        "title": title,
        "description": None,
        "tags": tags,
        "media_type": media_type,
        "media_path": media_ref,
        "media_available": media_file_is_readable(media_ref),
        "category_l1": category_l1,
        "category_l2": category_l2,
        "concept": concept,
        "latitude": _optional_float(obj.get("source_latitude")),
        "longitude": _optional_float(obj.get("source_longitude")),
        "source_user_photo_count": (
            int(obj["source_user_photo_count"]) if obj.get("source_user_photo_count") is not None else None
        ),
        "popularity_score": round(pop_score, 2),
        "ingested_at_utc": ingested_at_utc,
    }


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def _pythonize(value: object) -> object:
    """Converts numpy/pandas scalars and NaN into JSON-native Python values."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, np.ndarray):
        return [_pythonize(item) for item in value.tolist()]
    if isinstance(value, list):
        return [_pythonize(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _strict_int_fields() -> set[str]:
    """Names of PostRecord fields typed StrictInt (optionally nullable)."""
    names: set[str] = set()
    for name, field in PostRecord.model_fields.items():
        annotation = field.annotation
        candidates = (annotation, *getattr(annotation, "__args__", ()))
        if any(candidate is StrictInt for candidate in candidates):
            names.add(name)
    return names


STRICT_INT_FIELDS = _strict_int_fields()


def _coerce_row_types(row: dict) -> dict:
    """Restores StrictInt fields that pandas widened to float (int column + NaN)."""
    coerced = dict(row)
    for name in STRICT_INT_FIELDS:
        value = coerced.get(name)
        if isinstance(value, float) and value.is_integer():
            coerced[name] = int(value)
    return coerced


def validate_against_schema(df: pd.DataFrame, sample_size: int = SCHEMA_SAMPLE_SIZE) -> dict:
    """Validates a deterministic sample of *final* rows against the PostRecord model.

    Running this after the history computation means the leakage-free prior
    columns are validated too, not just the raw-derived ones.
    """
    if df.empty:
        return {"validated_rows": 0, "sample_step": 1}
    step = max(1, len(df) // sample_size)
    errors: list[str] = []
    validated = 0
    for position in range(0, len(df), step):
        row = _coerce_row_types(
            {key: _pythonize(value) for key, value in df.iloc[position].to_dict().items()}
        )
        try:
            PostRecord.model_validate(row)
        except Exception as exc:  # pydantic ValidationError reported with its row index
            errors.append(f"row {position}: {exc}")
            if len(errors) >= 5:
                break
        validated += 1
    if errors:
        raise ValueError("PostRecord schema validation failed:\n" + "\n".join(errors))
    return {"validated_rows": validated, "sample_step": step}


def assert_column_contract(columns: list[str]) -> None:
    """Asserts the written columns are exactly what the PostRecord schema declares."""
    schema_fields = set(PostRecord.model_fields.keys())
    written = set(columns)
    unknown = written - schema_fields
    if unknown:
        raise ValueError(f"normalizer wrote columns absent from PostRecord: {sorted(unknown)}")
    missing = schema_fields - written - set(OPTIONAL_UNWRITTEN_FIELDS)
    if missing:
        raise ValueError(f"PostRecord fields missing from the normalized output: {sorted(missing)}")


def assert_dataset_guardrails(df: pd.DataFrame, expected_raw_valid_row_count: int) -> None:
    """Fails the run when demo rows or row-count drift sneak into the dataset."""
    assert (df["source"] == SOURCE_ID).all(), "non-smpd_real source rows present"
    assert not df["user_id"].isin(DEMO_USER_IDS).any(), "demo user rows present in training dataset"
    assert len(df) == expected_raw_valid_row_count, (
        f"row count drift: {len(df)} != {expected_raw_valid_row_count} valid raw rows"
    )
    assert df["post_id"].is_unique, "duplicate post_id rows present"


def build_quality_report(
    df: pd.DataFrame,
    *,
    raw_row_count: int,
    valid_row_count: int,
    skipped_invalid_rows: int,
    raw_file_sha256: str,
) -> dict:
    """Builds the data-quality/provenance report (plan §1.1.5, §5.2.A)."""
    demo_row_count = int(df["user_id"].isin(DEMO_USER_IDS).sum())
    return {
        "raw_row_count": int(raw_row_count),
        "valid_row_count": int(valid_row_count),
        "total_posts": int(len(df)),
        "unique_posts": int(df["post_id"].nunique()),
        "unique_users": int(df["user_id"].nunique()),
        "skipped_invalid_rows": int(skipped_invalid_rows),
        "demo_row_count": demo_row_count,
        "source_counts": df["source"].value_counts().to_dict(),
        "raw_file_sha256": raw_file_sha256,
        "mean_popularity": round(float(df["popularity_score"].mean()), 3),
        "std_popularity": round(float(df["popularity_score"].std()), 3),
        "min_popularity": round(float(df["popularity_score"].min()), 3),
        "max_popularity": round(float(df["popularity_score"].max()), 3),
        "media_type_distribution": df["media_type"].value_counts().to_dict(),
        "media_available_rows": int(df["media_available"].sum()),
        "timezone_basis_distribution": df["timezone_basis"].value_counts().to_dict(),
        "local_hour_covered": sorted(int(h) for h in df["local_hour"].dropna().unique()),
        "date_range": [
            str(pd.to_datetime(df["published_at_utc"]).min()),
            str(pd.to_datetime(df["published_at_utc"]).max()),
        ],
        "null_percentages": {
            col: round(float(df[col].isna().mean() * 100), 2) for col in df.columns
        },
    }


def normalize_dataset(raw_file: Path = RAW_FILE, output_parquet: Path = OUTPUT_PARQUET) -> dict:
    started = time.time()
    print(f"Reading raw records from {raw_file}...")

    records: list[dict] = []
    raw_row_count = 0
    skipped = 0
    ingested_at_utc = datetime.now(timezone.utc)

    # The previous output is deliberately never read: re-importing it is how the
    # removed demo fixtures used to creep back into the training set (plan §1.1.2).
    with open(raw_file, "r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            line = line.strip()
            if not line:
                continue
            raw_row_count += 1
            record = normalize_record(json.loads(line), ingested_at_utc=ingested_at_utc)
            if record is None:
                skipped += 1
                continue
            records.append(record)
            if (index + 1) % 100000 == 0:
                print(f"Processed {index + 1:,} rows...")

    valid_row_count = len(records)
    print(f"Read {raw_row_count:,} raw rows -> {valid_row_count:,} valid rows (skipped {skipped:,}).")

    df = pd.DataFrame(records, columns=OUTPUT_COLUMNS)
    assert_column_contract(list(df.columns))

    print("Computing leakage-free chronological user history priors...")
    df = compute_leakage_free_history(df, default_popularity_mean=5.5)

    # Guardrails run on the final frame, after every transformation that could
    # have introduced demo rows or dropped/duplicated records.
    assert_dataset_guardrails(df, expected_raw_valid_row_count=valid_row_count)

    validation_report = validate_against_schema(df)
    print(f"Validated {validation_report['validated_rows']} sampled rows against PostRecord.")

    output_parquet.parent.mkdir(parents=True, exist_ok=True)
    print(f"Saving {len(df):,} records to {output_parquet}...")
    df.to_parquet(output_parquet, index=False)

    raw_file_sha256 = file_sha256(raw_file)
    report = build_quality_report(
        df,
        raw_row_count=raw_row_count,
        valid_row_count=valid_row_count,
        skipped_invalid_rows=skipped,
        raw_file_sha256=raw_file_sha256,
    )
    provenance = {
        "git_commit": git_commit_sha(),
        "normalized_at_utc": utc_now_iso(),
        "raw_file": str(raw_file),
        "output_parquet": str(output_parquet),
        "output_parquet_sha256": file_sha256(output_parquet),
        "schema_validation": validation_report,
        "elapsed_seconds": round(time.time() - started, 2),
    }
    write_json_with_provenance(REPORT_PATH, report, provenance)

    print("=" * 60)
    print("Normalization complete")
    print(f"Valid rows:            {report['valid_row_count']:,}")
    print(f"Demo rows:             {report['demo_row_count']}")
    print(f"Source counts:         {report['source_counts']}")
    print(f"Timezone basis:        {report['timezone_basis_distribution']}")
    print(f"Media available rows:  {report['media_available_rows']:,} (files are not shipped with the corpus)")
    print(f"Dataset sha256:        {provenance['output_parquet_sha256'][:16]}...")
    print(f"Report saved to:       {REPORT_PATH}")
    print("=" * 60)
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-file", type=Path, default=RAW_FILE)
    parser.add_argument("--output", type=Path, default=OUTPUT_PARQUET)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    normalize_dataset(raw_file=args.raw_file, output_parquet=args.output)
