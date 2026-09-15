"""Layer A — base-potential model, plus the window recommendation entry point.

The service is split along the two layers of the plan:

* **Layer A (`_prepare_features` + the LightGBM booster)** predicts how much
  performance a post can reach from its *content and account history alone*.
  It deliberately contains **no** time-of-day feature: no `hour`, `weekday`,
  `month`, cyclical encodings or `cat_x_hour` / `cat_x_weekday` /
  `history_x_hour` interactions. `account_baseline` is the residual *offset*,
  never an input.
* **Layer B (`TimeLiftTable`)** answers the window question, with support counts
  and uncertainty, in `backend/services/time_lift.py`.

`recommend_windows()` is the only production entry point; it never returns a
single "best hour".
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline

from backend.config import settings
from backend.schemas.media import MediaAnalysis
from backend.schemas.post import MediaTypeEnum
from backend.schemas.recommendation import (
    FeatureImportanceEntry,
    ModelMetricsResponse,
    RecommendedWindow,
    WindowRecommendation,
)
from backend.services.candidate_generator import build_candidate_windows
from backend.services.canonical_taxonomy import CATEGORY_CODE_MAP, classify_post_category
from backend.services.media_analysis import TEXT_CATEGORY_NO_MATCH_CONFIDENCE
from backend.services.tag_taxonomy import align_tags
from backend.services.time_features import resolve_user_timezone
from backend.services.time_lift import (
    BUCKETS_PER_DAY,
    CONFIDENCE_LOW,
    TimeLiftConfig,
    TimeLiftTable,
    WindowScore,
    confidence_tr,
    decide_windows,
)

logger = logging.getLogger(__name__)

# --- Layer A feature groups (plan §3.2) -------------------------------------
# Base-potential features only. Time-of-day features are intentionally absent.
CATEGORY_FEATURES = [
    "primary_cat_code",
    "primary_subcat_code",
    "primary_cat_confidence",
    "has_secondary_cat",
]

CONTEXT_FEATURES = [
    "context_source_code",
]

TAG_FEATURES = [
    "aligned_tag_count",
    "mismatched_tag_count",
    "unknown_tag_count",
    "generic_tag_count",
    "nsfw_tag_count",
    "semantic_tag_ratio",
    "unknown_tag_ratio",
    "tag_category_entropy",
]

MEDIA_FEATURES = [
    "media_type_code",
]

HISTORY_FEATURES = [
    "history_depth_code",
]

TEXT_SVD_FEATURES = [f"text_svd_{i}" for i in range(8)]

# Data-quality context, not a time-of-day signal: it records that the timestamp
# behind a row is a UTC fallback rather than a real local time.
DATA_QUALITY_FEATURES = [
    "timezone_basis_fallback",
]

# Feature sets that the training script trains and compares. A2/A3 are the only
# production candidates; A4 (legacy) exists for the same-protocol comparison.
A2_FEATURES = (
    CATEGORY_FEATURES + CONTEXT_FEATURES + TAG_FEATURES + TEXT_SVD_FEATURES
    + HISTORY_FEATURES + DATA_QUALITY_FEATURES
)
A3_FEATURES = A2_FEATURES + MEDIA_FEATURES

BASE_FEATURES = A3_FEATURES

# Name kept for callers that still import FEATURE_COLUMNS; it now refers to the
# base-potential contract, because time features are gone from the model.
FEATURE_COLUMNS = BASE_FEATURES

TEXT_SVD_PATH = settings.ARTIFACTS_DIR / "text_svd_model.joblib"

# Used when no time-lift artifact exists: every lookup returns neutral lift with
# no support, which the decision rule turns into a low-confidence broad window.
NEUTRAL_TIME_LIFT = TimeLiftTable()


def compute_account_baseline(
    user_post_count_prior: int,
    user_popularity_mean_prior: float,
    global_prior_mean: float,
    category_train_median: float | None = None,
    alpha: float = 10.0,
) -> float:
    """Shrunk account-level offset: the user's prior mean pulled to the global mean."""
    n = user_post_count_prior
    if n == 0:
        return category_train_median if category_train_median is not None else global_prior_mean
    return (n * user_popularity_mean_prior + alpha * global_prior_mean) / (n + alpha)


def get_history_depth_code(user_post_count_prior: int) -> int:
    if user_post_count_prior == 0:
        return 0  # cold_start
    if user_post_count_prior <= 5:
        return 1  # very_low_history
    if user_post_count_prior <= 20:
        return 2  # low_history
    if user_post_count_prior <= 100:
        return 3  # medium_history
    return 4  # high_history


class RecommendationService:
    """Serves base potential (Layer A) and time windows (Layer B)."""

    def __init__(
        self,
        model_path: Path | None = None,
        time_lift_path: Path | None = None,
        metrics_path: Path | None = None,
    ):
        self.model_path = model_path or settings.MODEL_PATH
        self.time_lift_path = time_lift_path or settings.TIME_LIFT_PATH
        self.metrics_path = metrics_path or settings.METRICS_PATH
        self.model: lgb.Booster | None = None
        self.svd_pipeline: Pipeline | None = None
        self.time_lift: TimeLiftTable | None = None
        self.metrics: dict[str, Any] = {}
        self.feature_names = BASE_FEATURES
        self.default_popularity = 5.8
        self.category_train_medians: dict[int, float] = {}
        self._load_training_metadata()
        self._load_svd_pipeline()
        self._load_time_lift()

    # ------------------------------------------------------------- loading
    def _load_training_metadata(self) -> None:
        if not self.metrics_path.exists():
            return
        try:
            metadata = json.loads(self.metrics_path.read_text(encoding="utf-8"))
            self.default_popularity = float(
                metadata.get("global_train_mean", metadata.get("global_train_median", self.default_popularity))
            )
            self.category_train_medians = {
                int(code): float(value)
                for code, value in metadata.get("category_train_medians", {}).items()
            }
        except (OSError, ValueError, TypeError):
            self.category_train_medians = {}

    def _load_svd_pipeline(self) -> None:
        if TEXT_SVD_PATH.exists():
            try:
                self.svd_pipeline = joblib.load(TEXT_SVD_PATH)
            except Exception as exc:  # pragma: no cover - corrupt artifact path
                logger.warning("failed to load SVD pipeline from %s: %s; text features degrade to zeros", TEXT_SVD_PATH, exc)

    def _load_time_lift(self) -> None:
        """Loads Layer B. A missing table degrades to neutral lift, never to a guess."""
        if not self.time_lift_path.exists():
            logger.warning(
                "time-lift table not found at %s; windows will be returned with neutral lift and low confidence",
                self.time_lift_path,
            )
            return
        try:
            self.time_lift = TimeLiftTable.load(self.time_lift_path)
            logger.info(
                "loaded time-lift table from %s (bucket_hours=%d, supported groups=%d)",
                self.time_lift_path,
                self.time_lift.config.bucket_hours,
                self.time_lift.coverage.get("supported_bucket_count", 0),
            )
        except Exception as exc:
            logger.warning("failed to load time-lift table from %s: %s", self.time_lift_path, exc)

    @property
    def time_lift_config(self) -> TimeLiftConfig:
        return self.time_lift.config if self.time_lift is not None else TimeLiftConfig()

    # ----------------------------------------------------------- features
    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Builds the **base-potential** feature matrix (no time features)."""
        X = pd.DataFrame(index=df.index)

        # 1. Data-quality context: was the local time real or a UTC fallback?
        if "timezone_basis" in df.columns:
            X["timezone_basis_fallback"] = (
                df["timezone_basis"].fillna("utc_fallback").astype(str) == "utc_fallback"
            ).astype(float)
        else:
            X["timezone_basis_fallback"] = (
                df.get("timezone_basis_fallback", pd.Series([0.0] * len(df), index=df.index))
                .fillna(0.0)
                .astype(float)
            )

        # 2. User/History features (account_baseline is computed separately as the
        #    residual offset; it is NOT a model input).
        post_counts = df.get("user_post_count_prior", pd.Series([0] * len(df), index=df.index)).fillna(0).astype(int)
        X["history_depth_code"] = post_counts.apply(get_history_depth_code).astype(float)

        # 3. Category & context features
        titles = df.get("title", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str)
        smpd_cats = df.get("smpd_category", df.get("category_l1", pd.Series([None] * len(df), index=df.index)))
        smpd_subcats = df.get("smpd_subcategory", df.get("category_l2", pd.Series([None] * len(df), index=df.index)))
        smpd_concepts = df.get("smpd_concept", df.get("concept", pd.Series([None] * len(df), index=df.index)))

        cat_codes: list[float] = []
        subcat_codes: list[float] = []
        cat_confs: list[float] = []
        has_secs: list[float] = []
        primary_categories: list[str] = []
        context_source_codes: list[float] = []

        for position in range(len(df)):
            class_res = classify_post_category(
                titles.iloc[position],
                smpd_cats.iloc[position],
                smpd_subcats.iloc[position],
                smpd_concepts.iloc[position],
            )
            cat_codes.append(float(class_res["primary_cat_code"]))
            subcat_codes.append(float(class_res["primary_subcat_code"]))
            cat_confs.append(float(class_res["primary_cat_confidence"]))
            has_secs.append(float(class_res["has_secondary_cat"]))
            primary_categories.append(str(class_res["primary_category"]))
            has_title = len(titles.iloc[position].strip()) >= 3
            has_taxonomy = any(
                value is not None and str(value).strip()
                for value in (smpd_cats.iloc[position], smpd_subcats.iloc[position], smpd_concepts.iloc[position])
            )
            context_source_codes.append(0.0 if has_title else (1.0 if has_taxonomy else 2.0))

        X["primary_cat_code"] = cat_codes
        X["primary_subcat_code"] = subcat_codes
        X["primary_cat_confidence"] = cat_confs
        X["has_secondary_cat"] = has_secs
        X["context_source_code"] = context_source_codes

        # 4. Tag features, classified against the post's own canonical category
        raw_tags_list = df.get("tags", pd.Series([[]] * len(df), index=df.index)).tolist()
        tag_features_dict: dict[str, list[float]] = {key: [] for key in TAG_FEATURES}
        combined_texts: list[str] = []

        for position, raw_tags in enumerate(raw_tags_list):
            safe_tags = list(raw_tags) if isinstance(raw_tags, (list, tuple, np.ndarray)) else []
            align_res = align_tags(safe_tags, context_category=int(cat_codes[position]))
            for key in TAG_FEATURES:
                tag_features_dict[key].append(float(align_res.get(key, 0.0)))
            # Context must remain independent from user-supplied tags.
            combined_texts.append(titles.iloc[position].strip())

        for key in TAG_FEATURES:
            X[key] = tag_features_dict[key]


        # 5. Latent Semantic Text SVD (8 dimensions)
        if self.svd_pipeline is not None:
            try:
                svd_matrix = self.svd_pipeline.transform(combined_texts)
            except Exception:
                svd_matrix = np.zeros((len(df), len(TEXT_SVD_FEATURES)))
        else:
            svd_matrix = np.zeros((len(df), len(TEXT_SVD_FEATURES)))

        for index in range(len(TEXT_SVD_FEATURES)):
            X[f"text_svd_{index}"] = svd_matrix[:, index]

        # 6. Media type
        media_types = df.get("media_type", pd.Series(["photo"] * len(df), index=df.index)).fillna("photo")
        mapping = {"photo": 0.0, "video": 1.0, "unknown": 2.0}
        X["media_type_code"] = media_types.apply(
            lambda value: mapping.get(value.value if hasattr(value, "value") else str(value), 2.0)
        )

        return X[self.feature_names]

    def account_baseline(self, df: pd.DataFrame, categories: np.ndarray | None = None) -> np.ndarray:
        """Builds the Layer A offset for every row (residual target = y - offset).

        Cold-start rows fall back to the **train-only** category median; without
        a category they get the global mean. `categories` may be passed
        explicitly when the caller already has the canonical category codes
        (e.g. after a media override).
        """
        post_counts = np.asarray(
            df.get("user_post_count_prior", pd.Series([0] * len(df), index=df.index)).fillna(0).astype(int)
        )
        pop_means = np.asarray(
            df.get("user_popularity_mean_prior", pd.Series([self.default_popularity] * len(df), index=df.index))
            .fillna(self.default_popularity)
            .astype(float)
        )
        baseline = np.array(
            [
                compute_account_baseline(int(count), float(mean), self.default_popularity)
                for count, mean in zip(post_counts, pop_means)
            ],
            dtype=float,
        )
        if self.category_train_medians and len(df):
            cold_mask = post_counts == 0
            if cold_mask.any():
                if categories is None:
                    categories = np.asarray(
                        df.get("primary_cat_code", pd.Series([10] * len(df), index=df.index))
                    )
                categories = np.asarray(categories)
                baseline[cold_mask] = [
                    self.category_train_medians.get(int(category), self.default_popularity)
                    for category in categories[cold_mask]
                ]
        return baseline

    # --------------------------------------------------------------- model
    @staticmethod
    def _load_booster_crlf_safe(model_path: Path) -> lgb.Booster:
        """Loads a booster tolerating CRLF line endings in the model text file.

        Checkouts with core.autocrlf can convert the model text to CRLF,
        which LightGBM's parser cannot read. Retry through a sanitized
        LF copy when the direct load fails.
        """
        try:
            return lgb.Booster(model_file=str(model_path))
        except Exception:
            text = model_path.read_text(encoding="utf-8")
            if "\r" not in text:
                raise
            import tempfile

            with tempfile.NamedTemporaryFile(
                "w", suffix=".txt", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(text.replace("\r\n", "\n").replace("\r", "\n"))
                tmp_path = Path(tmp.name)
            try:
                return lgb.Booster(model_file=str(tmp_path))
            finally:
                tmp_path.unlink(missing_ok=True)

    def train_or_load(self, df: pd.DataFrame) -> None:
        """Loads the saved base-potential model, otherwise fits an offline fallback."""
        if self.model_path.exists():
            try:
                loaded = self._load_booster_crlf_safe(self.model_path)
                if loaded.num_feature() != len(self.feature_names):
                    logger.warning(
                        "ignoring incompatible model: %d features, expected %d",
                        loaded.num_feature(), len(self.feature_names),
                    )
                    return
                self.model = loaded
                logger.info("loaded existing base-potential model from %s", self.model_path)
                return
            except Exception as exc:
                logger.warning("failed to load model from %s: %s", self.model_path, exc)

        if df.empty or len(df) < 10:
            return

        df_sorted = df.sort_values("published_at_utc").reset_index(drop=True)
        X = self._prepare_features(df_sorted)
        baseline = self.account_baseline(df_sorted)
        y = pd.to_numeric(df_sorted["popularity_score"], errors="coerce").fillna(self.default_popularity).values
        residual_y = y - baseline

        n = len(df_sorted)
        train_end = int(n * 0.70)
        val_end = int(n * 0.85)

        model = lgb.LGBMRegressor(
            objective="regression_l1",
            n_estimators=500,
            learning_rate=0.05,
            num_leaves=127,
            min_child_samples=20,
            subsample=0.85,
            colsample_bytree=0.8,
            reg_alpha=0.0,
            reg_lambda=5.0,
            random_state=42,
            n_jobs=-1,
            verbosity=-1,
        )
        model.fit(
            X.iloc[:train_end],
            residual_y[:train_end],
            eval_set=[(X.iloc[train_end:val_end], residual_y[train_end:val_end])],
            callbacks=[lgb.early_stopping(50, verbose=False)],
        )

        self.model = model.booster_
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        self.model.save_model(str(self.model_path))
        logger.info("trained and saved fallback base-potential model to %s (rows=%d)", self.model_path, len(df_sorted))

    def get_metrics(self) -> ModelMetricsResponse:
        """Returns offline final-evaluation metrics and feature importance."""
        metrics_file = self.metrics_path
        if metrics_file.exists():
            try:
                self.metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        base = self.metrics.get("base_potential", {})
        fi_entries = [
            FeatureImportanceEntry(feature=entry["feature"], importance=float(entry["importance"]))
            for entry in self.metrics.get("feature_importance", [])
        ]
        return ModelMetricsResponse(
            baseline_mae=float(base.get("baseline_mae", 0.0)),
            baseline_spearman=float(base.get("baseline_spearman", 0.0)),
            model_mae=float(base.get("mae", 0.0)),
            model_spearman=float(base.get("spearman", 0.0)),
            feature_importance=fi_entries,
        )

    # ---------------------------------------------------------- inference
    @staticmethod
    def _apply_media_category(X: pd.DataFrame, media_context: MediaAnalysis | None) -> bool:
        """Overrides the text-derived category with a confident image category."""
        if media_context is None or media_context.canonical_category is None:
            return False
        code = CATEGORY_CODE_MAP.get(media_context.canonical_category)
        if code is None:
            return False
        X["primary_cat_code"] = float(code)
        X["primary_cat_confidence"] = float(media_context.category_confidence)
        return True

    @staticmethod
    def _apply_topic_category(X: pd.DataFrame, topic: str) -> bool:
        """Fills the category from the user's topic when the text matched nothing.

        `_prepare_features` only ever classifies the post title, so on the live
        paths -- where the quick endpoint passes `title=""` and an advisor idea
        often misses every keyword -- the category collapsed to the generic
        fallback. The topic was already carried on every call and simply never
        read, which is why declared interests changed nothing but a label.

        A text match always outranks the topic: it describes this post, whereas
        the topic describes the account.
        """
        if not topic:
            return False
        if float(X["primary_cat_confidence"].iloc[0]) > TEXT_CATEGORY_NO_MATCH_CONFIDENCE:
            return False
        result = classify_post_category(topic, None, None, None)
        confidence = float(result["primary_cat_confidence"])
        if confidence <= TEXT_CATEGORY_NO_MATCH_CONFIDENCE:
            return False
        code = CATEGORY_CODE_MAP.get(str(result["primary_category"]))
        if code is None:
            return False
        X["primary_cat_code"] = float(code)
        X["primary_cat_confidence"] = confidence
        return True

    def predict_base_potential(
        self,
        *,
        user_prior_mean: float,
        user_post_count: int,
        title: str = "",
        tags: list[str] | None = None,
        topic: str = "",
        media_type: MediaTypeEnum = MediaTypeEnum.PHOTO,
        media_context: MediaAnalysis | None = None,
        timezone_basis_fallback: bool = False,
    ) -> tuple[float, int]:
        """Returns (base_potential, primary_category_code) for one candidate post.

        The value does not depend on when the post is published: that is exactly
        the separation the plan asks for.
        """
        frame = pd.DataFrame([
            {
                "user_post_count_prior": float(user_post_count),
                "user_popularity_mean_prior": float(user_prior_mean),
                "title": title,
                "tags": tags or [],
                "media_type": media_type,
                "timezone_basis": "utc_fallback" if timezone_basis_fallback else "source_offset",
            }
        ])
        X = self._prepare_features(frame)
        self._apply_topic_category(X, topic)
        # Runs last: a confident image outranks both the idea text and the topic.
        self._apply_media_category(X, media_context)
        category_code = int(X["primary_cat_code"].iloc[0])
        baseline = float(self.account_baseline(frame, categories=X["primary_cat_code"].to_numpy())[0])

        if self.model is None:
            return baseline, category_code

        residual = float(self.model.predict(X)[0])
        return baseline + residual, category_code

    def recommend_windows(
        self,
        *,
        user_prior_mean: float,
        user_post_count: int,
        title: str = "",
        tags: list[str] | None = None,
        media_type: MediaTypeEnum = MediaTypeEnum.PHOTO,
        topic: str = "Yapay Zeka",
        days_ahead: int = 7,
        max_windows: int = 3,
        timezone_name: str | None = None,
        utc_offset_minutes: int | None = None,
        media_context: MediaAnalysis | None = None,
    ) -> WindowRecommendation:
        """Scores the local 3-hour windows of the next `days_ahead` days.

        Returns the recommended windows with their observational lift, support,
        evidence level and the confidence decided by `decide_windows`. When the
        evidence is not strong enough, every returned window is flagged as a
        broad window instead of being presented as the best hour.
        """
        user_tz = resolve_user_timezone(timezone_name, utc_offset_minutes)
        now_local = datetime.now(timezone.utc).astimezone(user_tz.tz)
        bucket_hours = self.time_lift_config.bucket_hours
        windows = build_candidate_windows(now_local, days_ahead=days_ahead, bucket_hours=bucket_hours)

        base_potential, primary_category_code = self.predict_base_potential(
            user_prior_mean=user_prior_mean,
            user_post_count=user_post_count,
            title=title,
            tags=tags,
            topic=topic,
            media_type=media_type,
            media_context=media_context,
            timezone_basis_fallback=user_tz.is_fallback,
        )

        table = self.time_lift
        scored: list[tuple[Any, WindowScore]] = []
        for window in windows:
            effective_table = table if table is not None else NEUTRAL_TIME_LIFT
            entry = effective_table.lookup(primary_category_code, window.weekday, window.bucket)
            scored.append((
                window,
                WindowScore(
                    weekday=window.weekday,
                    bucket=window.bucket,
                    lift=entry.mean_lift,
                    evidence_level=entry.evidence_level,
                    support_post_count=entry.support_post_count,
                    support_user_count=entry.support_user_count,
                    ci_low=entry.ci_low,
                    ci_high=entry.ci_high,
                    eligible=entry.eligible and table is not None,
                ),
            ))

        history_depth = get_history_depth_code(user_post_count)
        selected = decide_windows(
            base_potential=base_potential,
            scored_windows=[score for _, score in scored],
            config=self.time_lift_config,
            cold_start=history_depth == 0,
            timezone_fallback=user_tz.is_fallback,
            max_windows=max_windows,
        )

        by_bucket_weekday = {(score.weekday, score.bucket): window for window, score in scored}
        mean_lift = float(np.mean([score.lift for _, score in scored])) if scored else 0.0

        recommended: list[RecommendedWindow] = []
        for score in selected:
            window = by_bucket_weekday[(score.weekday, score.bucket)]
            recommended.append(
                RecommendedWindow(
                    window_start_local=window.local_start,
                    window_end_local=window.local_end,
                    window_start_utc=window.utc_start,
                    window_end_utc=window.utc_end,
                    weekday=score.weekday_label,
                    weekday_index=score.weekday,
                    bucket=score.bucket,
                    time_range_local=score.range_label,
                    base_potential=round(base_potential, 3),
                    observational_time_lift=round(score.lift, 4),
                    relative_potential=round(score.lift - mean_lift, 4),
                    confidence=score.confidence,
                    confidence_label=confidence_tr(score.confidence),
                    support_post_count=score.support_post_count,
                    support_user_count=score.support_user_count,
                    evidence_level=score.evidence_level,
                    lift_ci_low=score.ci_low,
                    lift_ci_high=score.ci_high,
                    is_tie_or_broad_window=score.is_tie_or_broad_window,
                    timezone_basis=user_tz.basis,
                )
            )

        return WindowRecommendation(
            base_potential=round(base_potential, 3),
            primary_category_code=primary_category_code,
            confidence=selected[0].confidence if selected else CONFIDENCE_LOW,
            confidence_label=confidence_tr(selected[0].confidence if selected else CONFIDENCE_LOW),
            is_tie_or_broad_window=bool(selected[0].is_tie_or_broad_window) if selected else True,
            timezone_basis=user_tz.basis,
            timezone_label=user_tz.label,
            timezone_fallback=user_tz.is_fallback,
            history_depth=get_history_depth_code(user_post_count),
            windows=recommended,
        )


__all__ = [
    "RecommendationService",
    "FEATURE_COLUMNS",
    "BASE_FEATURES",
    "A2_FEATURES",
    "A3_FEATURES",
    "CATEGORY_FEATURES",
    "CONTEXT_FEATURES",
    "TAG_FEATURES",
    "MEDIA_FEATURES",
    "HISTORY_FEATURES",
    "TEXT_SVD_FEATURES",
    "DATA_QUALITY_FEATURES",
    "compute_account_baseline",
    "get_history_depth_code",
    "BUCKETS_PER_DAY",
]
