"""Data-pipeline guardrails: demo rows, media truthfulness, schema alignment.

Covers plan §1.1 (demo protection), §1.3 (data contract) and the corresponding
acceptance criteria.
"""
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from backend.schemas.post import OPTIONAL_UNWRITTEN_FIELDS, PostRecord

NORMALIZER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "02_normalize_smp.py"


def _load_normalizer():
    """Loads scripts/02_normalize_smp.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("normalize_smp", NORMALIZER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def normalizer():
    return _load_normalizer()


def _raw_record(**overrides) -> dict:
    record = {
        "post_id": "1",
        "user_id": "42@N1",
        "published_at_utc": "2016-02-09T18:00:00Z",
        "timezone_offset": "+03:00",
        "source_timezone_id": None,
        "text": "Test post",
        "tags": ["tech", "AI"],
        "media_type": "photo",
        "media_ref": "train/42@N1/1.jpg",
        "source_media_status": "ready",
        "source_category_l1": "Tech",
        "source_category_l2": None,
        "source_concept": None,
        "source_latitude": 0.0,
        "source_longitude": None,
        "source_user_photo_count": 12.0,
        "target_popularity": 7.5,
    }
    record.update(overrides)
    return record


def test_normalize_record_produces_local_time_and_basis(normalizer):
    from datetime import datetime, timezone

    row = normalizer.normalize_record(_raw_record(), ingested_at_utc=datetime.now(timezone.utc))

    assert row["source"] == "smpd_real"
    assert row["local_hour"] == 21  # 18:00 UTC with +03:00
    assert row["local_weekday"] == 1  # Tuesday
    assert row["timezone_basis"] == "source_offset"
    assert row["local_datetime"].tzinfo is None  # wall clock, not tz-aware


def test_normalize_record_without_offset_is_marked_as_fallback(normalizer):
    from datetime import datetime, timezone

    row = normalizer.normalize_record(
        _raw_record(timezone_offset=None), ingested_at_utc=datetime.now(timezone.utc)
    )

    assert row["timezone_basis"] == "utc_fallback"
    assert row["local_hour"] == 18
    assert row["timezone_offset"] is None


def test_unknown_media_type_is_not_coerced_to_photo(normalizer):
    from datetime import datetime, timezone

    row = normalizer.normalize_record(
        _raw_record(media_type="gif"), ingested_at_utc=datetime.now(timezone.utc)
    )
    assert row["media_type"] == "unknown"


def test_media_available_requires_a_readable_file(normalizer, tmp_path):
    """The source status flag alone must not make media_available True."""
    from datetime import datetime, timezone

    ready_but_missing = normalizer.normalize_record(
        _raw_record(source_media_status="ready"), ingested_at_utc=datetime.now(timezone.utc)
    )
    assert ready_but_missing["media_available"] is False

    real_file = tmp_path / "train" / "42@N1"
    real_file.mkdir(parents=True)
    (real_file / "1.jpg").write_bytes(b"\xff\xd8\xff")
    assert normalizer.media_file_is_readable("train/42@N1/1.jpg", media_root=tmp_path) is True
    assert normalizer.media_file_is_readable(None, media_root=tmp_path) is False


def test_dataset_guardrails_reject_demo_rows(normalizer):
    """A demo row in the frame must fail the run, not be silently trained on."""
    demo_user = sorted(normalizer.DEMO_USER_IDS)[0]
    frame = pd.DataFrame({
        "source": [normalizer.SOURCE_ID, normalizer.SOURCE_ID],
        "user_id": ["42@N1", demo_user],
        "post_id": ["1", "2"],
    })

    with pytest.raises(AssertionError, match="demo user"):
        normalizer.assert_dataset_guardrails(frame, expected_raw_valid_row_count=2)


def test_dataset_guardrails_reject_foreign_sources_and_row_drift(normalizer):
    foreign = pd.DataFrame({
        "source": ["ensosyal_demo"],
        "user_id": ["real_user"],
        "post_id": ["1"],
    })
    with pytest.raises(AssertionError, match="smpd_real"):
        normalizer.assert_dataset_guardrails(foreign, expected_raw_valid_row_count=1)

    ok = pd.DataFrame({"source": [normalizer.SOURCE_ID], "user_id": ["real_user"], "post_id": ["1"]})
    with pytest.raises(AssertionError, match="row count drift"):
        normalizer.assert_dataset_guardrails(ok, expected_raw_valid_row_count=2)


def test_normalizer_never_reads_the_previous_output():
    """The demo re-injection path must not come back (plan §1.1.2)."""
    source = NORMALIZER_PATH.read_text(encoding="utf-8")
    assert "read_parquet" not in source
    assert "existing_df" not in source


def test_normalizer_writes_exactly_the_post_record_columns(normalizer):
    schema_fields = set(PostRecord.model_fields)
    written = set(normalizer.OUTPUT_COLUMNS)

    assert written - schema_fields == set()
    assert schema_fields - written == set(OPTIONAL_UNWRITTEN_FIELDS)


def test_written_dataframe_validates_against_post_record(normalizer):
    """Sample validation is a real check: a wrong type must fail the run."""
    from datetime import datetime, timezone

    row = normalizer.normalize_record(_raw_record(), ingested_at_utc=datetime.now(timezone.utc))
    row["user_post_count_prior"] = 0
    row["user_popularity_mean_prior"] = 0.0
    frame = pd.DataFrame([row], columns=normalizer.OUTPUT_COLUMNS)

    report = normalizer.validate_against_schema(frame, sample_size=10)
    assert report["validated_rows"] == 1

    # A string where a float belongs must fail the run, not be coerced.
    broken_row = dict(row)
    broken_row["popularity_score"] = "7.5"
    broken = pd.DataFrame([broken_row], columns=normalizer.OUTPUT_COLUMNS)
    with pytest.raises(ValueError, match="PostRecord schema validation failed"):
        normalizer.validate_against_schema(broken, sample_size=10)

    # An unknown timezone basis must fail too.
    basis_row = dict(row)
    basis_row["timezone_basis"] = "guessed"
    broken_basis = pd.DataFrame([basis_row], columns=normalizer.OUTPUT_COLUMNS)
    with pytest.raises(ValueError, match="PostRecord schema validation failed"):
        normalizer.validate_against_schema(broken_basis, sample_size=10)


def test_source_user_photo_count_is_provenance_only():
    """It is stored, but it must never enter the model feature set."""
    from backend.schemas.post import PROVENANCE_ONLY_COLUMNS
    from backend.services.recommendation import BASE_FEATURES

    assert "source_user_photo_count" in PROVENANCE_ONLY_COLUMNS
    assert "source_user_photo_count" not in BASE_FEATURES


def test_data_quality_report_shape(tmp_path):
    """The report must carry the provenance fields the plan requires (§1.1.5)."""
    report_path = Path("data/reports/data_quality.json")
    if not report_path.exists():
        pytest.skip("data/reports/data_quality.json not generated in this checkout")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["demo_row_count"] == 0
    assert report["source_counts"] == {"smpd_real": report["valid_row_count"]}
    assert report["total_posts"] == report["valid_row_count"]
    assert len(report["raw_file_sha256"]) == 64
    assert set(report["timezone_basis_distribution"]) <= {"source_offset", "utc_fallback"}
    provenance = report.get("provenance", {})
    assert provenance.get("schema_validation", {}).get("validated_rows", 0) > 0
    assert provenance.get("output_parquet_sha256")
