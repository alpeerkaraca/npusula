import { ApiError } from "../apiClient.js";
const string = (value) => typeof value === "string" && value.trim().length > 0;
const number = (value) => typeof value === "number" && Number.isFinite(value);
const percent = (value) => number(value) && value >= 0 && value <= 100;
const unit = (value) => number(value) && value >= 0 && value <= 1;
const count = (value) => number(value) && value >= 0;
const nullableNumber = (value) => value === null || number(value);
const flag = (value) => typeof value === "boolean";
const date = (value) => string(value) && !Number.isNaN(Date.parse(value));
const texts = (value) => Array.isArray(value) && value.every(string);
// The backend models confidence as a level plus a Turkish label, not as a
// 0-100 percentage, so the contract validates the level verbatim.
const LEVELS = ["high", "medium", "low"];
const level = (value) => LEVELS.includes(value);
const slot = (value) =>
  value &&
  ["id", "day", "time", "timeZone", "confidenceLabel", "evidenceLevel"].every(
    (key) => string(value[key]),
  ) &&
  date(value.startsAt) &&
  level(value.confidence) &&
  // Both of these are signed popularity-score residuals, so neither is bounded
  // to 0-1; only the derived rank is a percentage.
  number(value.relativePotential) &&
  percent(value.rankPercent) &&
  count(value.supportPostCount) &&
  count(value.supportUserCount) &&
  number(value.observationalTimeLift) &&
  nullableNumber(value.liftCiLow) &&
  nullableNumber(value.liftCiHigh);
const similarPost = (value) =>
  value &&
  string(value.postId) &&
  typeof value.title === "string" &&
  // The backend sends a numeric weekday index here, not a day name.
  count(value.weekdayIndex) &&
  value.weekdayIndex <= 6 &&
  count(value.hour) &&
  number(value.popularityScore) &&
  number(value.similarity) &&
  texts(value.tags);
const validators = {
  profile: (v) =>
    v &&
    texts(v.interests) &&
    v.interests.length >= 2 &&
    v.interests.length <= 5,
  job: (v) =>
    v &&
    string(v.id) &&
    ["queued", "running", "completed", "failed"].includes(v.status) &&
    percent(v.progress) &&
    typeof v.message === "string",
  recommendations: (v) =>
    v &&
    level(v.confidence) &&
    string(v.confidenceLabel) &&
    date(v.updatedAt) &&
    string(v.activeTopic) &&
    flag(v.coldStart) &&
    string(v.timezoneBasis) &&
    typeof v.explanation === "string" &&
    Array.isArray(v.slots) &&
    v.slots.length <= 3 &&
    v.slots.every(slot),
  analysis: (v) =>
    v &&
    string(v.id) &&
    string(v.modelVersion) &&
    string(v.topic) &&
    string(v.primaryCategory) &&
    unit(v.primaryCategoryConfidence) &&
    level(v.confidence) &&
    string(v.confidenceLabel) &&
    string(v.bestTime) &&
    string(v.alternativeTime) &&
    texts(v.hashtags) &&
    string(v.tip) &&
    string(v.historyDepth) &&
    flag(v.isTieOrBroadWindow) &&
    string(v.timezoneBasis) &&
    Array.isArray(v.windows) &&
    v.windows.length <= 3 &&
    v.windows.every(slot) &&
    Array.isArray(v.similarPosts) &&
    v.similarPosts.every(similarPost),
  plan: (v) =>
    v &&
    string(v.id) &&
    string(v.slotId) &&
    date(v.startsAt) &&
    ["scheduled", "saved"].includes(v.status),
  draft: (v) =>
    v &&
    string(v.id) &&
    string(v.text) &&
    ["video", "image", "thread"].includes(v.format),
};
export function validate(kind, value) {
  if (!validators[kind]?.(value))
    throw new ApiError("Servis yanıtı beklenen veri sözleşmesine uymuyor.", {
      code: "INVALID_RESPONSE",
    });
  return value;
}
export function validateAnalysisInput({ text, format }) {
  if (
    !string(text) ||
    text.trim().length > 500 ||
    !["video", "image", "thread"].includes(format)
  )
    throw new ApiError(
      "1–500 karakter arasında içerik ve geçerli bir format seçin.",
      { code: "VALIDATION" },
    );
}
