import { ApiError, createApiClient } from "../apiClient.js";
import { validate, validateAnalysisInput } from "./contracts.js";
import { config } from "../../config.js";

// Budgets and the window time zone live in src/config.js; this module holds no
// tunables of its own.
/**
 * The backend models media as photo | video | unknown. A "thread" is text-only
 * and genuinely has no media, so it is reported as unknown rather than being
 * described to the model as a photo.
 */
const MEDIA_TYPE_BY_FORMAT = {
  video: "video",
  image: "photo",
  thread: "unknown",
};
export const USER_ID_KEY = "npusula-user-id";

/** Mints the anonymous identity used when no account has been chosen. */
export function mintUserId() {
  try {
    return `web-${crypto.randomUUID().slice(0, 12)}`;
  } catch {
    return "web-anonymous";
  }
}

/**
 * Points this browser at a specific account. The backend has no auth or user
 * registry: the id in localStorage *is* the identity, so writing it here is
 * what switches accounts. Requests re-read it (see `createBackendPusulaApi`),
 * which is why this alone is enough to change who the next call is for.
 */
export function setUserId(userId, storage = globalThis.localStorage) {
  try {
    storage?.setItem(USER_ID_KEY, userId);
  } catch {
    // A blocked storage must not break the switch; the in-memory id still wins
    // for this session because the caller also holds it in React state.
  }
  return userId;
}

const stripHash = (tag) => String(tag).replace(/^#+/, "");

/**
 * 0-100 position of each score within the returned set. The backend's
 * `relative_potential` is a signed residual centred on the corpus mean, so it
 * cannot drive a bar directly; this rank is plain arithmetic over real values
 * and is labelled as a rank wherever it is shown.
 */
function rankPercents(values) {
  const min = Math.min(...values);
  const span = Math.max(...values) - min;
  return values.map((value) =>
    span === 0 ? 50 : ((value - min) / span) * 100,
  );
}

/**
 * `POST /api/media/analyze` -> contract `MediaAnalysis`.
 * `topic` and `canonicalCategory` stay null when CLIP fell below its floors.
 */
export function toMediaAnalysis(response) {
  return {
    mediaId: response.media_id,
    mediaKind: response.media_kind,
    filename: response.filename,
    sizeBytes: response.size_bytes,
    framesAnalyzed: response.frames_analyzed,
    durationSeconds: response.duration_seconds ?? null,
    width: response.width,
    height: response.height,
    topic: response.topic ?? null,
    topicConfidence: response.topic_confidence,
    canonicalCategory: response.canonical_category ?? null,
    categoryConfidence: response.category_confidence,
    categoryMargin: response.category_margin,
    suggestedTags: response.suggested_tags || [],
    uncertain: response.uncertain,
    modelName: response.model_name,
  };
}

/** Backend `RecommendedWindow` -> contract `Slot`. Field-for-field, no invention. */
export function toSlot(window, timeZone, rankPercent) {
  return {
    id: `${window.weekday_index}-${window.bucket}`,
    day: window.weekday,
    time: window.time_range_local,
    startsAt: window.window_start_utc,
    timeZone,
    relativePotential: window.relative_potential,
    rankPercent,
    supportPostCount: window.support_post_count,
    supportUserCount: window.support_user_count,
    observationalTimeLift: window.observational_time_lift,
    liftCiLow: window.lift_ci_low ?? null,
    liftCiHigh: window.lift_ci_high ?? null,
    confidence: window.confidence,
    confidenceLabel: window.confidence_label,
    evidenceLevel: window.evidence_level,
  };
}

/** Maps the backend's window list, attaching the derived bar rank. */
export function toSlots(windows, timeZone) {
  const list = windows || [];
  const ranks = rankPercents(list.map((window) => window.relative_potential));
  return list.map((window, index) => toSlot(window, timeZone, ranks[index]));
}

const NO_WINDOW = "Uygun pencere bulunamadı";
const describeWindow = (slot) => (slot ? `${slot.day} ${slot.time}` : NO_WINDOW);

export function toSimilarPost(post) {
  return {
    postId: post.post_id,
    title: post.title,
    weekdayIndex: post.weekday,
    hour: post.hour,
    popularityScore: post.popularity_score,
    similarity: post.similarity,
    tags: post.tags || [],
  };
}

/**
 * `GET /api/sample-users` -> contract `SampleUser[]`.
 *
 * `historyDepth` is the backend's label for the account's real corpus row
 * count, not for the 30-post evidence window the advisor scores — so it
 * separates "rich history" from "no history" even though both may behave the
 * same downstream.
 */
export function toSampleUsers(response) {
  const users = Array.isArray(response?.users) ? response.users : [];
  return users.map((user) => ({
    userId: user.user_id,
    postCount: user.post_count,
    historyDepth: user.history_depth,
  }));
}

/** `GET /api/recommend/quick/{user_id}` -> contract `Recommendations`. */
export function toRecommendations(
  response,
  { timeZone = config.timeZone, receivedAt = new Date().toISOString() } = {},
) {
  return {
    confidence: response.confidence,
    confidenceLabel: response.confidence_label,
    // The backend exposes no server timestamp; this is when the client got it.
    updatedAt: receivedAt,
    activeTopic: response.active_topic,
    coldStart: response.cold_start,
    timezoneBasis: response.timezone_basis,
    explanation: response.explanation,
    slots: toSlots(response.windows, timeZone),
  };
}

/** `POST /api/recommend/advisor` -> contract `Analysis`. */
export function toAnalysis(response, { timeZone = config.timeZone } = {}) {
  const windows = toSlots(response.windows, timeZone);
  return {
    id: response.request_id,
    modelVersion: response.model_version,
    topic: response.topic,
    primaryCategory: response.primary_category,
    primaryCategoryConfidence: response.primary_category_confidence,
    textCategory: response.text_category,
    categorySource: response.category_source,
    mediaAnalysis: response.media_analysis
      ? toMediaAnalysis(response.media_analysis)
      : null,
    confidence: response.confidence,
    // The advisor carries the label on each window, not on the envelope.
    confidenceLabel: windows[0]?.confidenceLabel || response.confidence,
    bestTime: describeWindow(windows[0]),
    alternativeTime: describeWindow(windows[1]),
    hashtags: (response.suggested_tags || []).map(stripHash),
    tip: response.explanation,
    historyDepth: response.history_depth,
    isTieOrBroadWindow: response.is_tie_or_broad_window,
    timezoneBasis: response.timezone_basis,
    windows,
    similarPosts: (response.similar_posts || []).map(toSimilarPost),
  };
}

/**
 * The setup wizard's interest ids mapped onto the backend's canonical topic
 * vocabulary (`backend/services/profile.py::TOPIC_SEEDS`). Two ids have no
 * exact counterpart and borrow the closest trained centroid:
 *   - `araba`: there is no automotive topic; "Teknoloji Trendleri" carries the
 *     lansman / akıllı cihaz / batarya / çip vocabulary.
 *   - `bilim`: "Eğitim" carries araştırma / akademi / üniversite / kitap.
 */
export const TOPIC_BY_INTEREST = {
  teknoloji: "Teknoloji Trendleri",
  araba: "Teknoloji Trendleri",
  yazilim: "Yazılım",
  oyun: "Oyun",
  yasam: "Yaşam",
  yapayzekâ: "Yapay Zeka",
  tasarim: "Kültür-Sanat",
  bilim: "Eğitim",
  girisimcilik: "Girişimcilik",
};
/** Every canonical topic this adapter can produce, for drift tests. */
export const TOPIC_VOCABULARY = [...new Set(Object.values(TOPIC_BY_INTEREST))];

/**
 * Canonical, deduplicated topics for a selection, preserving its order — the
 * backend derives `active_topic` from the first declared topic, so order is
 * meaningful. Several ids can collapse onto one topic (teknoloji + araba).
 */
export function mapInterests(interests) {
  const topics = [];
  for (const interest of interests || []) {
    const topic = TOPIC_BY_INTEREST[String(interest).normalize("NFC")];
    if (topic && !topics.includes(topic)) topics.push(topic);
  }
  return topics;
}

/** Stable per-browser identity; the backend has no auth or user registry. */
export function resolveUserId(storage = globalThis.localStorage) {
  try {
    const existing = storage?.getItem(USER_ID_KEY);
    if (existing) return existing;
    const created = mintUserId();
    storage?.setItem(USER_ID_KEY, created);
    return created;
  } catch {
    return "web-anonymous";
  }
}

/**
 * Talks to the NPusula FastAPI backend and shapes its answers into the contract
 * the UI renders. `baseUrl` is `/api`, which already matches the backend's own
 * route prefix, so request paths are backend-native.
 *
 * `userId` pins the identity for the lifetime of the adapter and is meant for
 * tests. Left unset, every request re-reads localStorage instead: the account
 * picker switches identity by writing that key, and a value captured once at
 * construction would keep sending requests as the previous account forever.
 * @returns {import('./types').PusulaApi}
 */
export function createBackendPusulaApi({
  baseUrl = config.apiBaseUrl,
  timeZone = config.timeZone,
  userId = null,
  fetchImpl,
} = {}) {
  const request = createApiClient({ baseUrl, fetchImpl });
  const currentUserId = () => userId || resolveUserId();
  const quickPath = () =>
    `/recommend/quick/${encodeURIComponent(currentUserId())}?timezone=${encodeURIComponent(timeZone)}`;
  return {
    mode: "http",
    async analyzeMedia(file, options) {
      const body = new FormData();
      body.append("file", file);
      const response = await request("/media/analyze", {
        ...options,
        method: "POST",
        body,
        timeoutMs: config.mediaUploadTimeoutMs,
      });
      return validate("mediaAnalysis", toMediaAnalysis(response));
    },
    async saveProfile(body, options) {
      validate("profile", body);
      const topics = mapInterests(body.interests);
      if (!topics.length)
        throw new ApiError("Seçilen ilgi alanları konu sözlüğüyle eşleşmedi.", {
          code: "VALIDATION",
        });
      const response = await request(
        `/profile/${encodeURIComponent(currentUserId())}/interests`,
        { ...options, method: "PUT", body: { topics } },
      );
      // Confirm the server really stored what we sent instead of reporting a
      // success the profile never received.
      const stored = new Set(response?.declared_topics || []);
      const missing = topics.filter((topic) => !stored.has(topic));
      if (missing.length)
        throw new ApiError(
          "Sunucu seçilen ilgi alanlarını kaydetmedi.",
          { code: "INVALID_RESPONSE" },
        );
      // The server keeps canonical topics; echoing the request preserves the
      // wizard's own vocabulary without a lossy topic -> id round-trip.
      return { interests: body.interests };
    },
    async startPreparation(body, options) {
      const id = options?.requestId || crypto.randomUUID();
      // There is no job queue: quick answers in ~30ms, so this single call is
      // the real work. Polling it would only simulate progress.
      await request(quickPath(), { ...options });
      return {
        id,
        status: "completed",
        progress: 100,
        message: "Profil ve rota hazır",
      };
    },
    async getPreparation(id) {
      return {
        id,
        status: "completed",
        progress: 100,
        message: "Profil ve rota hazır",
      };
    },
    async getRecommendations(options) {
      const response = await request(quickPath(), options);
      return validate("recommendations", toRecommendations(response, { timeZone }));
    },
    async analyzeIdea(body, options) {
      validateAnalysisInput(body);
      const response = await request("/recommend/advisor", {
        ...options,
        method: "POST",
        timeoutMs: config.advisorTimeoutMs,
        body: {
          user_id: currentUserId(),
          idea: body.text,
          media_type: MEDIA_TYPE_BY_FORMAT[body.format] || "photo",
          horizon: "next_7_days",
          timezone: timeZone,
          // When present the backend lets the image own the canonical category.
          ...(body.mediaId ? { media_id: body.mediaId } : {}),
        },
      });
      return validate("analysis", toAnalysis(response, { timeZone }));
    },
    async listSampleUsers(options) {
      const response = await request("/sample-users", options);
      return validate("sampleUsers", toSampleUsers(response));
    },
    async createPlan(body, options) {
      const response = await request("/plans", {
        ...options,
        method: "POST",
        body: {
          slot_id: body.slotId,
          starts_at: body.startsAt,
          time_zone: body.timeZone,
          text: body.text,
          format: body.format,
        },
      });
      return validate("plan", {
        id: response.id,
        slotId: response.slot_id,
        startsAt: response.starts_at,
        status: response.status,
      });
    },
    async saveDraft(body, options) {
      const response = await request("/drafts", {
        ...options,
        method: "POST",
        body: { text: body.text, format: body.format },
      });
      return validate("draft", {
        id: response.id,
        text: response.text,
        format: response.format,
      });
    },
  };
}
