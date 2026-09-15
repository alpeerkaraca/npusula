/** Formatting helpers shared by the NPusula result components. */

/** Turkish renderings of the backend's evidence levels. */
const EVIDENCE_LABELS = {
  category_weekday_bucket: "Kategori + gün/saat",
  category_bucket: "Kategori + saat dilimi",
  global_weekday_bucket: "Genel + gün/saat",
  global_bucket: "Genel + saat dilimi",
  neutral: "Nötr",
};

/**
 * Signed score, NOT a percentage. The backend's `observational_time_lift` and
 * `relative_potential` are residuals in popularity-score units
 * (backend/services/recommendation.py:588-589), so they are rendered as plain
 * signed numbers. Calling them "%" would misstate the unit.
 */
export const signedScore = (value) =>
  `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(2)}`;

/**
 * Score-unit interval. The confidence level is not assumed: the table ships
 * its own `ci_level`, so the label stays unit-neutral.
 */
export const scoreInterval = (low, high) =>
  low === null || high === null || low === undefined || high === undefined
    ? null
    : `Güven aralığı [${signedScore(low)}, ${signedScore(high)}]`;

export const evidenceLabel = (level) => EVIDENCE_LABELS[level] || level;
