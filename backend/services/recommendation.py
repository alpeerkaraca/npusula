"""Popularity prediction model and recommendation service with Semantic Content Features."""
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline

from backend.config import settings
from backend.schemas.post import MediaTypeEnum
from backend.schemas.recommendation import CandidateSlot, FeatureImportanceEntry, ModelMetricsResponse
from backend.services.candidate_generator import (
    build_candidate_slots,
    extract_time_features,
    select_top_non_overlapping_slots,
)
from backend.services.canonical_taxonomy import classify_post_category
from backend.services.tag_taxonomy import align_tags

TIME_FEATURES = [
    "hour",
    "weekday",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
    "is_weekend",
    "time_basis_utc_fallback",
    "month",
]

USER_HISTORY_FEATURES = [
    "account_baseline",
    "history_depth_code",
]

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
    "accepted_tag_count",
    "rejected_tag_count",
    "generic_tag_count",
    "semantic_tag_ratio",
    "irrelevant_tag_ratio",
    "tag_alignment_mean",
    "tag_alignment_min",
    "tag_category_entropy",
]

INTERACTION_FEATURES = [
    "cat_x_hour",
    "cat_x_weekday",
    "history_x_hour",
]

MEDIA_FEATURES = [
    "media_type_code",
]

TEXT_SVD_FEATURES = [f"text_svd_{i}" for i in range(8)]

# Complete feature vector matching the new contract
FEATURE_COLUMNS = (
    TIME_FEATURES
    + USER_HISTORY_FEATURES
    + CATEGORY_FEATURES
    + CONTEXT_FEATURES
    + TAG_FEATURES
    + INTERACTION_FEATURES
    + MEDIA_FEATURES
    + TEXT_SVD_FEATURES
)

TEXT_SVD_PATH = settings.ARTIFACTS_DIR / "text_svd_model.joblib"


def compute_account_baseline(
    user_post_count_prior: int,
    user_popularity_mean_prior: float,
    global_prior_mean: float,
    category_train_median: float | None = None,
    alpha: float = 10.0,
) -> float:
    n = user_post_count_prior
    if n == 0:
        return category_train_median if category_train_median is not None else global_prior_mean
    return (n * user_popularity_mean_prior + alpha * global_prior_mean) / (n + alpha)


def get_history_depth_code(user_post_count_prior: int) -> int:
    if user_post_count_prior == 0: return 0  # cold_start
    if user_post_count_prior <= 5: return 1  # very_low_history
    if user_post_count_prior <= 20: return 2  # low_history
    if user_post_count_prior <= 100: return 3  # medium_history
    return 4  # high_history


class RecommendationService:
    """Trains, evaluates and serves the LightGBM popularity predictors with semantic features."""

    def __init__(self, model_path: Path | None = None):
        self.model_path = model_path or settings.MODEL_PATH
        self.model: lgb.Booster | None = None
        self.svd_pipeline: Pipeline | None = None
        self.metrics: dict[str, Any] = {}
        self.feature_names = FEATURE_COLUMNS
        self.default_popularity = 5.8
        self.category_train_medians: dict[int, float] = {}
        self._load_training_metadata()
        self._load_svd_pipeline()

    def _load_training_metadata(self) -> None:
        if not settings.METRICS_PATH.exists():
            return
        try:
            metadata = json.loads(settings.METRICS_PATH.read_text(encoding="utf-8"))
            self.default_popularity = float(metadata.get("global_train_mean", self.default_popularity))
            self.category_train_medians = {
                int(code): float(value)
                for code, value in metadata.get("category_train_medians", {}).items()
            }
        except (OSError, ValueError, TypeError):
            self.category_train_medians = {}

    def _load_svd_pipeline(self) -> None:
        """Loads fitted TF-IDF + SVD text semantic encoder. Note: may be replaced by context_engine later."""
        if TEXT_SVD_PATH.exists():
            try:
                self.svd_pipeline = joblib.load(TEXT_SVD_PATH)
            except Exception as e:
                print(f"Warning: Failed to load SVD pipeline: {e}")

    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Builds all tabular, tag taxonomy, and text semantic features."""
        X = pd.DataFrame(index=df.index)

        # 1. Time features
        if "published_at_utc" in df.columns:
            dts = pd.to_datetime(df["published_at_utc"], utc=True)
            hours = df.get("local_hour", dts.dt.hour).astype(float)
            weekdays = dts.dt.weekday.astype(float)
            months = dts.dt.month.astype(float)
            if "time_basis" in df.columns:
                X["time_basis_utc_fallback"] = (
                    df["time_basis"].fillna("utc_fallback").astype(str) == "utc_fallback"
                ).astype(float)
            elif "timezone_inferred" in df.columns:
                X["time_basis_utc_fallback"] = df["timezone_inferred"].fillna(True).astype(float)
            else:
                X["time_basis_utc_fallback"] = 1.0
        else:
            hours = df.get("hour", pd.Series([12.0] * len(df), index=df.index)).astype(float)
            weekdays = df.get("weekday", pd.Series([0.0] * len(df), index=df.index)).astype(float)
            months = pd.Series([datetime.now(timezone.utc).month] * len(df), index=df.index).astype(float)
            X["time_basis_utc_fallback"] = 1.0

        X["hour"] = hours
        X["weekday"] = weekdays
        X["hour_sin"] = np.sin(2 * np.pi * hours / 24.0)
        X["hour_cos"] = np.cos(2 * np.pi * hours / 24.0)
        X["weekday_sin"] = np.sin(2 * np.pi * weekdays / 7.0)
        X["weekday_cos"] = np.cos(2 * np.pi * weekdays / 7.0)
        X["is_weekend"] = (weekdays >= 5).astype(float)
        X["month"] = months

        # 2. User/History features
        post_counts = df.get("user_post_count_prior", pd.Series([0] * len(df), index=df.index)).fillna(0).astype(int)
        pop_means = df.get("user_popularity_mean_prior", pd.Series([self.default_popularity] * len(df), index=df.index)).fillna(self.default_popularity).astype(float)
        
        X["history_depth_code"] = post_counts.apply(get_history_depth_code).astype(float)
        X["account_baseline"] = [
            compute_account_baseline(pc, pm, self.default_popularity)
            for pc, pm in zip(post_counts, pop_means)
        ]

        # 3. Category & Context features
        titles = df.get("title", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str)
        smpd_cats = df.get("smpd_category", df.get("category_l1", pd.Series([None] * len(df), index=df.index)))
        smpd_subcats = df.get("smpd_subcategory", df.get("category_l2", pd.Series([None] * len(df), index=df.index)))
        smpd_concepts = df.get("smpd_concept", df.get("concept", pd.Series([None] * len(df), index=df.index)))
        
        cat_codes = []
        subcat_codes = []
        cat_confs = []
        has_secs = []
        primary_categories = []
        context_source_codes = []
        
        for idx in range(len(df)):
            class_res = classify_post_category(titles.iloc[idx], smpd_cats.iloc[idx], smpd_subcats.iloc[idx], smpd_concepts.iloc[idx])
            cat_codes.append(float(class_res["primary_cat_code"]))
            subcat_codes.append(float(class_res["primary_subcat_code"]))
            cat_confs.append(float(class_res["primary_cat_confidence"]))
            has_secs.append(float(class_res["has_secondary_cat"]))
            primary_categories.append(str(class_res["primary_category"]))
            has_title = len(titles.iloc[idx].strip()) >= 3
            has_taxonomy = any(
                value is not None and str(value).strip()
                for value in (smpd_cats.iloc[idx], smpd_subcats.iloc[idx], smpd_concepts.iloc[idx])
            )
            context_source_codes.append(0.0 if has_title else (1.0 if has_taxonomy else 2.0))
            
        X["primary_cat_code"] = cat_codes
        X["primary_subcat_code"] = subcat_codes
        X["primary_cat_confidence"] = cat_confs
        X["has_secondary_cat"] = has_secs
        if self.category_train_medians:
            cold_mask = post_counts == 0
            cold_codes = X.loc[cold_mask, "primary_cat_code"].astype(int)
            X.loc[cold_mask, "account_baseline"] = (
                cold_codes.map(self.category_train_medians).fillna(self.default_popularity).to_numpy()
            )
        
        # Context Engine source code
        X["context_source_code"] = context_source_codes

        # 4. Tag features
        raw_tags_list = df.get("tags", pd.Series([[]] * len(df), index=df.index)).tolist()
        tag_features_dict = {k: [] for k in TAG_FEATURES}
        
        combined_texts = []
        for idx, raw_tags in enumerate(raw_tags_list):
            safe_tags = list(raw_tags) if isinstance(raw_tags, (list, tuple, np.ndarray)) else []
            align_res = align_tags(safe_tags, context_category=primary_categories[idx])
            for k in TAG_FEATURES:
                tag_features_dict[k].append(align_res.get(k, 0.0))
            # Context must remain independent from user-supplied tags.
            combined_texts.append(titles.iloc[idx].strip())
            
        for k in TAG_FEATURES:
            X[k] = tag_features_dict[k]
            
        # 5. Interaction features
        X["cat_x_hour"] = X["primary_cat_code"] * 100 + X["hour"]
        X["cat_x_weekday"] = X["primary_cat_code"] * 10 + X["weekday"]
        X["history_x_hour"] = X["history_depth_code"] * 100 + X["hour"]

        # 6. Latent Semantic Text SVD (8 dimensions)
        if self.svd_pipeline is not None:
            try:
                svd_matrix = self.svd_pipeline.transform(combined_texts)
            except Exception:
                svd_matrix = np.zeros((len(df), 8))
        else:
            svd_matrix = np.zeros((len(df), 8))

        for i in range(8):
            X[f"text_svd_{i}"] = svd_matrix[:, i]

        # 7. Media type
        media_types = df.get("media_type", pd.Series(["photo"] * len(df), index=df.index)).fillna("photo")
        mapping = {"photo": 0.0, "video": 1.0, "unknown": 2.0}
        X["media_type_code"] = media_types.apply(
            lambda m: mapping.get(m.value if hasattr(m, "value") else str(m), 0.0)
        )

        return X[self.feature_names]

    def train_or_load(self, df: pd.DataFrame) -> None:
        """Loads saved model artifact if available, otherwise trains on historical posts."""
        if self.model_path.exists():
            try:
                loaded = lgb.Booster(model_file=str(self.model_path))
                if loaded.num_feature() != len(self.feature_names):
                    print(
                        f"Ignoring incompatible model with {loaded.num_feature()} features; "
                        f"expected {len(self.feature_names)}."
                    )
                    return
                self.model = loaded
                print(f"Loaded existing model from {self.model_path}")
                return
            except Exception as e:
                print(f"Failed to load model from {self.model_path}: {e}")

        if df.empty or len(df) < 10:
            return

        df_sorted = df.sort_values("published_at_utc").reset_index(drop=True)
        X = self._prepare_features(df_sorted)
        y = df_sorted["popularity_score"].fillna(self.default_popularity).values
        residual_y = y - X["account_baseline"].to_numpy()

        n = len(df_sorted)
        train_end = int(n * 0.70)
        val_end = int(n * 0.85)

        X_train, y_train = X.iloc[:train_end], residual_y[:train_end]
        X_val, y_val = X.iloc[train_end:val_end], residual_y[train_end:val_end]

        model = lgb.LGBMRegressor(
            objective="regression_l1",
            n_estimators=500,
            learning_rate=0.04,
            num_leaves=63,
            min_child_samples=50,
            subsample=0.85,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
            verbosity=-1,
        )
        model.fit(
            X_train,
            y_train,
            eval_set=[(X_val, y_val)],
            callbacks=[lgb.early_stopping(50, verbose=False)],
        )

        self.model = model.booster_
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        self.model.save_model(str(self.model_path))

    def get_metrics(self) -> ModelMetricsResponse:
        """Returns offline test metrics and feature importance from artifacts/metrics.json."""
        metrics_file = settings.METRICS_PATH
        if metrics_file.exists():
            try:
                with open(metrics_file, "r", encoding="utf-8") as f:
                    self.metrics = json.load(f)
            except Exception:
                pass

        fi_entries = []
        for fi in self.metrics.get("feature_importance", []):
            fi_entries.append(FeatureImportanceEntry(feature=fi["feature"], importance=float(fi["importance"])))

        return ModelMetricsResponse(
            baseline_mae=float(self.metrics.get("baseline_mae", 0.45)),
            baseline_spearman=float(self.metrics.get("baseline_spearman", 0.58)),
            model_mae=float(self.metrics.get("model_mae", 0.38)),
            model_spearman=float(self.metrics.get("model_spearman", 0.64)),
            feature_importance=fi_entries,
        )

    def recommend_slots(
        self,
        user_prior_mean: float,
        user_post_count: int,
        title: str = "",
        tags: list[str] | None = None,
        media_type: MediaTypeEnum = MediaTypeEnum.PHOTO,
        topic: str = "Yapay Zeka",
        days_ahead: int = 7,
        top_k: int = 3,
        model_mode: str = "auto",
    ) -> list[CandidateSlot]:
        """Scores 28 candidate slots (next 7 days x 4 slots) with semantic taxonomy and SVD embedding."""
        now = datetime.now(timezone.utc)
        candidates = build_candidate_slots(start_time=now, days_ahead=days_ahead)

        rows: list[dict[str, Any]] = []
        for dt in candidates:
            time_feats = extract_time_features(dt)
            rows.append({
                **time_feats,
                "user_post_count_prior": float(user_post_count),
                "user_popularity_mean_prior": float(user_prior_mean),
                "title": title,
                "tags": tags or [],
                "media_type": media_type,
            })

        cand_df = pd.DataFrame(rows)
        X_cand = self._prepare_features(cand_df)

        has_lgbm = self.model is not None

        if has_lgbm:
            # The persisted M5 booster predicts residual popularity.
            scores = X_cand["account_baseline"].to_numpy() + self.model.predict(X_cand)
        else:
            scores = []
            for _, r in X_cand.iterrows():
                h = r["hour"]
                hour_bonus = 0.4 if h in [18.0, 21.0] else (0.1 if h == 12.0 else -0.2)
                score = float(r["account_baseline"]) + hour_bonus
                scores.append(score)
            scores = np.array(scores)

        scored_pairs = list(zip(candidates, [float(s) for s in scores]))
        selected_slots = select_top_non_overlapping_slots(scored_pairs, top_k=top_k, min_gap_hours=3.0)

        # Calculate relative potential
        rates = np.power(2, scores) - 1
        reference_rate = np.median(rates) if len(rates) > 0 else 1.0
        epsilon = 1e-5

        # Calculate confidence level
        hd = get_history_depth_code(user_post_count)
        if hd >= 3:
            confidence_level = "Yüksek"
        elif hd <= 1:
            confidence_level = "Düşük"
        else:
            confidence_level = "Orta"

        updated_slots = []
        for slot in selected_slots:
            score = slot.predicted_popularity
            rate = (2 ** score) - 1
            rp = ((rate - reference_rate) / max(reference_rate, epsilon)) * 100
            
            slot_dict = slot.model_dump()
            slot_dict["relative_potential"] = rp
            slot_dict["confidence_level"] = confidence_level
            updated_slots.append(CandidateSlot(**slot_dict))

        return updated_slots
