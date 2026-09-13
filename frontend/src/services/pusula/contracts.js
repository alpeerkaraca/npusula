import { ApiError } from "../apiClient.js";
const string = (value) => typeof value === "string" && value.trim().length > 0;
const number = (value) => typeof value === "number" && Number.isFinite(value);
const percent = (value) => number(value) && value >= 0 && value <= 100;
const date = (value) => string(value) && !Number.isNaN(Date.parse(value));
const texts = (value) => Array.isArray(value) && value.every(string);
const slot = (value) =>
  value &&
  ["id", "day", "time", "timeZone", "format", "label"].every((key) =>
    string(value[key]),
  ) &&
  date(value.startsAt) &&
  percent(value.onlinePercent) &&
  number(value.reach) &&
  value.reach >= 0;
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
    percent(v.confidence) &&
    date(v.updatedAt) &&
    Array.isArray(v.slots) &&
    v.slots.length <= 3 &&
    v.slots.every(slot),
  analysis: (v) =>
    v &&
    string(v.id) &&
    string(v.modelVersion) &&
    percent(v.confidence) &&
    number(v.reachMin) &&
    v.reachMin >= 0 &&
    number(v.reachMax) &&
    v.reachMax >= v.reachMin &&
    number(v.saveMultiplier) &&
    v.saveMultiplier >= 0 &&
    percent(v.commentProbability) &&
    number(v.liftPercent) &&
    string(v.bestTime) &&
    string(v.alternativeTime) &&
    texts(v.hashtags) &&
    string(v.tip) &&
    string(v.draft),
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
