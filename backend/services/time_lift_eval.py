"""Held-out evaluation of the time-lift layer (plan §5.2.C).

These metrics are *observational generalisation* metrics. They answer "did the
windows the table ranks highest actually show higher residual lift in the locked
test window?", never "is this the causally best hour".

Every metric is computed by replaying the production decision path
(`decide_windows`) on the test rows, so the reported tie/no-claim rate and the
confidence report describe what users would actually have been shown.
"""
from __future__ import annotations

from collections import defaultdict
import math

import numpy as np

from backend.services.time_features import BUCKETS_PER_DAY
from backend.services.time_lift import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    TimeLiftConfig,
    TimeLiftTable,
    WindowScore,
    decide_windows,
)


def _safe_spearman(x: np.ndarray, y: np.ndarray) -> float | None:
    if x.size < 3 or y.size < 3:
        return None
    if np.all(x == x[0]) or np.all(y == y[0]):
        return None
    from scipy.stats import spearmanr

    value = spearmanr(x, y).statistic
    if value is None or not np.isfinite(value):
        return None
    return float(value)


def _observed_bucket_means(frame) -> dict[tuple[int, int, int], float]:
    sums: dict[tuple[int, int, int], float] = defaultdict(float)
    counts: dict[tuple[int, int, int], int] = defaultdict(int)
    for category, weekday, bucket, residual in zip(
        frame["category_code"], frame["local_weekday"], frame["bucket"], frame["residual"]
    ):
        key = (int(category), int(weekday), int(bucket))
        sums[key] += float(residual)
        counts[key] += 1
    return {key: sums[key] / counts[key] for key in sums}


def _window_scores_for_row(table: TimeLiftTable, category: int, weekday: int) -> list[WindowScore]:
    scores: list[WindowScore] = []
    for bucket in range(BUCKETS_PER_DAY):
        entry = table.lookup(category, weekday, bucket)
        scores.append(
            WindowScore(
                weekday=weekday,
                bucket=bucket,
                lift=entry.mean_lift,
                evidence_level=entry.evidence_level,
                support_post_count=entry.support_post_count,
                support_user_count=entry.support_user_count,
                ci_low=entry.ci_low,
                ci_high=entry.ci_high,
                eligible=entry.eligible,
            )
        )
    return scores


def evaluate_windows(
    table: TimeLiftTable,
    test_frame,
    base_predictions: np.ndarray,
    config: TimeLiftConfig,
    *,
    min_group_support: int | None = None,
) -> dict:
    """Computes the held-out observational metrics for the time-lift layer.

    `test_frame` must carry category_code, local_weekday, bucket, user_id,
    residual (observed y - base prediction) and the flags `cold_start` /
    `timezone_fallback`. `base_predictions` are the locked base-model outputs for
    the same rows (used for the product-level reporting).
    """
    support_bar = min_group_support if min_group_support is not None else config.min_support_posts
    observed_means = _observed_bucket_means(test_frame)

    categories = test_frame["category_code"].to_numpy(dtype=int)
    weekdays = test_frame["local_weekday"].to_numpy(dtype=int)
    buckets = test_frame["bucket"].to_numpy(dtype=int)
    residuals = test_frame["residual"].to_numpy(dtype=float)
    cold_flags = test_frame["cold_start"].to_numpy(dtype=bool)
    tz_flags = test_frame["timezone_fallback"].to_numpy(dtype=bool)

    predicted_lifts = np.zeros(len(test_frame), dtype=float)
    confidence_counts = {CONFIDENCE_HIGH: 0, CONFIDENCE_MEDIUM: 0, CONFIDENCE_LOW: 0}
    confidence_positive = {CONFIDENCE_HIGH: [0, 0], CONFIDENCE_MEDIUM: [0, 0], CONFIDENCE_LOW: [0, 0]}
    tie_count = 0
    top1_hits = 0
    top3_hits = 0
    top1_positive = 0
    evaluated_rows = 0
    recommended_observed_lifts: list[float] = []
    baseline_observed_lifts: list[float] = []
    recommended_lift_deltas: list[float] = []
    ndcg_scores: list[float] = []
    regrets: list[float] = []
    precision_pairs: list[tuple[float, float]] = []

    grouped_rows: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index in range(len(test_frame)):
        grouped_rows[(int(categories[index]), int(weekdays[index]))].append(index)

    for (category, weekday), row_indices in grouped_rows.items():
        scores = _window_scores_for_row(table, category, weekday)
        supported = [window for window in scores if window.eligible]
        observed_at_best = None
        gains: dict[int, float] = {}
        idcg = 0.0
        if supported:
            best_supported = max(
                supported,
                key=lambda window: observed_means.get((category, weekday, window.bucket), float("-inf")),
            )
            observed_at_best = observed_means.get((category, weekday, best_supported.bucket))
            gains = {
                window.bucket: max(
                    0.0, observed_means.get((category, weekday, window.bucket), 0.0)
                )
                for window in supported
            }
            ideal_gains = sorted(gains.values(), reverse=True)[:3]
            idcg = sum(gain / math.log2(rank + 2) for rank, gain in enumerate(ideal_gains))

        for index in row_indices:
            row_bucket = int(buckets[index])
            row_score_entry = next(window for window in scores if window.bucket == row_bucket)
            predicted_lifts[index] = row_score_entry.lift

            selected = decide_windows(
                base_potential=0.0,
                scored_windows=scores,
                config=config,
                cold_start=bool(cold_flags[index]),
                timezone_fallback=bool(tz_flags[index]),
            )
            chosen = selected[0]
            confidence_counts[chosen.confidence] += 1
            if chosen.is_tie_or_broad_window:
                tie_count += 1

            chosen_observed = observed_means.get((category, weekday, chosen.bucket))
            if chosen_observed is not None:
                positive = 1 if chosen_observed > 0 else 0
                confidence_positive[chosen.confidence][1] += 1
                confidence_positive[chosen.confidence][0] += positive
                precision_pairs.append((chosen_observed, chosen.lift))
                recommended_observed_lifts.append(chosen_observed)

            if row_score_entry.eligible:
                evaluated_rows += 1
                # Reference point for the recommendation: what an arbitrary
                # supported window of this (category, weekday) would have given.
                # Groups selected by their train estimate regress towards the
                # mean on held-out data, so an absolute lift below zero is
                # expected and only the delta against this baseline is readable.
                if chosen_observed is not None:
                    supported_observed = [
                        observed_means[(category, weekday, window.bucket)]
                        for window in supported
                        if (category, weekday, window.bucket) in observed_means
                    ]
                    if supported_observed:
                        baseline_mean = float(np.mean(supported_observed))
                        baseline_observed_lifts.append(baseline_mean)
                        recommended_lift_deltas.append(chosen_observed - baseline_mean)
                ranked_supported = sorted(supported, key=lambda window: window.lift, reverse=True)
                top1_hits += int(ranked_supported[0].bucket == row_bucket)
                top3_hits += int(row_bucket in {window.bucket for window in ranked_supported[:3]})

                if chosen_observed is not None:
                    top1_positive += int(chosen_observed > 0)

                dcg = 0.0
                for rank, window in enumerate(ranked_supported[:3]):
                    gain = gains.get(window.bucket, 0.0)
                    if gain:
                        dcg += gain / math.log2(rank + 2)
                if idcg > 0:
                    ndcg_scores.append(dcg / idcg)

                if observed_at_best is not None and chosen_observed is not None:
                    regrets.append(observed_at_best - chosen_observed)

    # Group-level Spearman: does the table's lift order match the order observed
    # in the locked test window?
    pooled_pairs = [
        (mean, table.lookup(*key).mean_lift)
        for key, mean in observed_means.items()
        if table.lookup(*key).support_post_count >= support_bar
    ]
    pooled_rho = (
        _safe_spearman(
            np.array([pair[1] for pair in pooled_pairs]),
            np.array([pair[0] for pair in pooled_pairs]),
        )
        if pooled_pairs
        else None
    )
    within_category_rhos: list[float] = []
    by_category: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for (category, weekday, bucket), mean in observed_means.items():
        entry = table.lookup(category, weekday, bucket)
        if entry.support_post_count >= support_bar:
            by_category[category].append((mean, entry.mean_lift))
    for pairs in by_category.values():
        rho = _safe_spearman(
            np.array([pair[1] for pair in pairs]), np.array([pair[0] for pair in pairs])
        )
        if rho is not None:
            within_category_rhos.append(rho)

    # CI coverage: does the reported interval contain the observed held-out mean?
    coverage_hits = 0
    coverage_total = 0
    for key, mean in observed_means.items():
        entry = table.lookup(*key)
        if entry.ci_low is None or entry.ci_high is None:
            continue
        if entry.support_post_count < support_bar:
            continue
        coverage_total += 1
        coverage_hits += int(entry.ci_low <= mean <= entry.ci_high)

    def _precision(level: str) -> float | None:
        hits, total = confidence_positive[level]
        return round(hits / total, 6) if total else None

    def _rate(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 6) if denominator else None

    total_rows = len(test_frame) or 1
    base_pred = np.asarray(base_predictions, dtype=float)
    return {
        "supported_bucket_count": table.coverage.get("supported_bucket_count", 0),
        "bucket_support_distribution": table.coverage.get("category_weekday_bucket_support", {}),
        "level_group_counts": table.coverage.get("level_group_counts", {}),
        "level_eligible_group_counts": table.coverage.get("level_eligible_group_counts", {}),
        "held_out_bucket_lift_mae": round(
            float(np.mean(np.abs(predicted_lifts - residuals))), 6
        ),
        "held_out_bucket_lift_spearman": (
            round(float(np.mean(within_category_rhos)), 6) if within_category_rhos else None
        ),
        "held_out_bucket_lift_spearman_pooled": None if pooled_rho is None else round(pooled_rho, 6),
        "observed_group_count": len(observed_means),
        "evaluated_rows_with_supported_group": evaluated_rows,
        "top1_actual_bucket_hit_rate": _rate(top1_hits, evaluated_rows),
        "top3_actual_bucket_hit_rate": _rate(top3_hits, evaluated_rows),
        "top1_positive_lift_hit_rate": _rate(top1_positive, evaluated_rows),
        "ndcg_at_3": round(float(np.mean(ndcg_scores)), 6) if ndcg_scores else None,
        "ndcg_rows": len(ndcg_scores),
        "mean_ranking_regret": round(float(np.mean(regrets)), 6) if regrets else None,
        "mean_ranking_regret_rows": len(regrets),
        "mean_recommended_observed_lift": (
            round(float(np.mean(recommended_observed_lifts)), 6) if recommended_observed_lifts else None
        ),
        "mean_recommended_observed_lift_rows": len(recommended_observed_lifts),
        "mean_observed_lift_supported_baseline": (
            round(float(np.mean(baseline_observed_lifts)), 6) if baseline_observed_lifts else None
        ),
        "mean_recommended_lift_delta_vs_baseline": (
            round(float(np.mean(recommended_lift_deltas)), 6) if recommended_lift_deltas else None
        ),
        "mean_recommended_lift_delta_rows": len(recommended_lift_deltas),
        "positive_lift_precision_by_confidence": {
            CONFIDENCE_HIGH: _precision(CONFIDENCE_HIGH),
            CONFIDENCE_MEDIUM: _precision(CONFIDENCE_MEDIUM),
            CONFIDENCE_LOW: _precision(CONFIDENCE_LOW),
        },
        "bootstrap_ci_coverage": _rate(coverage_hits, coverage_total),
        "bootstrap_ci_coverage_groups": coverage_total,
        "tie_or_no_claim_rate": round(tie_count / total_rows, 6),
        "confidence_rate": {
            level: round(count / total_rows, 6) for level, count in confidence_counts.items()
        },
        "base_prediction_mean": round(float(np.mean(base_pred)), 6) if base_pred.size else None,
    }
