"""The canonical ingestion contract shared by every data source.

Both data paths — the SMPD normalizer (`scripts/02_normalize_smp.py`) and the
NSosyal adapter (`backend/adapters/nsosyal.py`) — write the same columns and
pass through the same gates. Keeping the contract in one module is what makes
plan §7 step 1 ("önce aynı canonical feature sözleşmesine normalize et") a
mechanical operation instead of a re-implementation.

Gates enforced for every source:
  * demo rows and foreign sources cannot enter the dataset,
  * every written column is declared by `PostRecord`, and every declared field
    is written (except the documented media-embedding fields),
  * a deterministic sample of final rows validates against the model.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import StrictInt

from backend.schemas.post import OPTIONAL_UNWRITTEN_FIELDS, PostRecord

SMPD_SOURCE_ID = "smpd_real"
NSOSYAL_SOURCE_ID = "nsosyal"
KNOWN_SOURCE_IDS = frozenset({SMPD_SOURCE_ID, NSOSYAL_SOURCE_ID})

DEMO_USER_IDS = frozenset({"demo_user_01", "demo_user_02", "demo_user_03"})

# Deterministic sample size for full-model validation of individual rows.
SCHEMA_SAMPLE_SIZE = 500

# Columns written by every ingestion path, in output order. Kept as an explicit
# list so the schema alignment check is a real check and not a tautology.
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


def media_file_is_readable(media_ref: str | None, media_root: Path) -> bool:
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


def add_leakage_free_priors(frame: pd.DataFrame, default_popularity_mean: float | None = None) -> pd.DataFrame:
    """Completes an ingested frame with the two leakage-free prior columns.

    Ingestion adapters map what the source *said*; the per-user priors are
    derived from the batch itself and must be recomputed chronologically, so they
    are added here rather than fabricated by the adapter. Training recomputes
    them again from the train window alone.
    """
    from backend.services.history_feature import compute_leakage_free_history

    if frame.empty:
        return frame
    fallback = default_popularity_mean
    if fallback is None:
        fallback = float(pd.to_numeric(frame["popularity_score"], errors="coerce").mean())
    completed = compute_leakage_free_history(frame, default_popularity_mean=fallback)
    return completed[OUTPUT_COLUMNS]


def optional_float(value: object) -> float | None:
    """Parses a source number, returning None for missing/non-finite values."""
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def pythonize(value: object) -> object:
    """Converts numpy/pandas scalars and NaN into JSON-native Python values."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, np.ndarray):
        return [pythonize(item) for item in value.tolist()]
    if isinstance(value, list):
        return [pythonize(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def assert_column_contract(columns: list[str]) -> None:
    """Asserts the written columns are exactly what the PostRecord schema declares."""
    schema_fields = set(PostRecord.model_fields.keys())
    written = set(columns)
    unknown = written - schema_fields
    if unknown:
        raise ValueError(f"ingestion wrote columns absent from PostRecord: {sorted(unknown)}")
    missing = schema_fields - written - set(OPTIONAL_UNWRITTEN_FIELDS)
    if missing:
        raise ValueError(f"PostRecord fields missing from the ingested output: {sorted(missing)}")


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
    columns are validated too, not just the source-derived ones.
    """
    if df.empty:
        return {"validated_rows": 0, "sample_step": 1}
    step = max(1, len(df) // sample_size)
    errors: list[str] = []
    validated = 0
    for position in range(0, len(df), step):
        row = _coerce_row_types(
            {key: pythonize(value) for key, value in df.iloc[position].to_dict().items()}
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


def assert_dataset_guardrails(
    df: pd.DataFrame,
    expected_raw_valid_row_count: int,
    allowed_sources: frozenset[str] = KNOWN_SOURCE_IDS,
) -> None:
    """Fails the run when demo rows, foreign sources or row-count drift appear."""
    unexpected = set(df["source"].unique()) - set(allowed_sources)
    assert not unexpected, (
        f"unexpected source values present: {sorted(unexpected)} (allowed: {sorted(allowed_sources)})"
    )
    assert not df["user_id"].isin(DEMO_USER_IDS).any(), "demo user rows present in training dataset"
    assert len(df) == expected_raw_valid_row_count, (
        f"row count drift: {len(df)} != {expected_raw_valid_row_count} valid raw rows"
    )
    assert df["post_id"].is_unique, "duplicate post_id rows present"


# Columns a source adapter does not produce: they are derived from the ingested
# batch (see `add_leakage_free_priors`).
DERIVED_PRIOR_COLUMNS = ("user_post_count_prior", "user_popularity_mean_prior")

# Columns an adapter maps directly from the source payload.
INGESTED_COLUMNS = [column for column in OUTPUT_COLUMNS if column not in DERIVED_PRIOR_COLUMNS]


__all__ = [
    "OUTPUT_COLUMNS",
    "INGESTED_COLUMNS",
    "DERIVED_PRIOR_COLUMNS",
    "add_leakage_free_priors",
    "SMPD_SOURCE_ID",
    "NSOSYAL_SOURCE_ID",
    "KNOWN_SOURCE_IDS",
    "DEMO_USER_IDS",
    "SCHEMA_SAMPLE_SIZE",
    "media_file_is_readable",
    "optional_float",
    "pythonize",
    "assert_column_contract",
    "validate_against_schema",
    "assert_dataset_guardrails",
    "STRICT_INT_FIELDS",
]
