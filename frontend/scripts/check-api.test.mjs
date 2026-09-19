import test from "node:test";
import assert from "node:assert/strict";
import { createApiClient } from "../src/services/apiClient.js";
import { createHttpPusulaApi } from "../src/services/pusula/httpAdapter.js";
import { createMockPusulaApi } from "../src/services/pusula/mockAdapter.js";
import {
  createBackendPusulaApi,
  mapInterests,
  resolveUserId,
  setUserId,
  toAnalysis,
  toMediaAnalysis,
  toRecommendations,
  toSampleUsers,
  TOPIC_VOCABULARY,
} from "../src/services/pusula/backendAdapter.js";
import { validate } from "../src/services/pusula/contracts.js";
const fixture = createMockPusulaApi({
  latency: 0,
  now: () => Date.parse("2026-09-14T00:00:00Z"),
});
const analysis = await fixture.analyzeIdea({
  text: "Backend sözleşmesi testi",
  format: "video",
});
test("HTTP request preserves payload, cookies and idempotency key", async () => {
  let captured;
  const api = createHttpPusulaApi({
    baseUrl: "/api",
    fetchImpl: async (url, options) => {
      captured = { url, options };
      return Response.json(analysis);
    },
  });
  const result = await api.analyzeIdea(
    {
      text: "Model girdisi",
      format: "video",
      interests: ["yazilim", "teknoloji"],
    },
    { requestId: "stable-key" },
  );
  assert.equal(captured.url, "/api/v1/pusula/analyses");
  assert.equal(captured.options.method, "POST");
  assert.equal(captured.options.credentials, "same-origin");
  assert.equal(captured.options.headers["Idempotency-Key"], "stable-key");
  assert.equal(JSON.parse(captured.options.body).text, "Model girdisi");
  assert.deepEqual(result, analysis);
});
test("HTTP errors never become demo results", async () => {
  for (const status of [401, 403, 429, 500]) {
    const api = createHttpPusulaApi({
      fetchImpl: async () => new Response("error", { status }),
    });
    await assert.rejects(
      () => api.getRecommendations(),
      (error) => error.status === status,
    );
  }
});
test("Guardrail error details from server response are preserved in ApiError", async () => {
  const guardrailMessage =
    "İçerik Güvenlik İhlali (Nefret Söylemi): Ayrımcılık veya nefret barındıran içerikler platformumuzda desteklenmemektedir.";
  const client = createApiClient({
    baseUrl: "/api",
    fetchImpl: async () =>
      new Response(JSON.stringify({ detail: guardrailMessage }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
  });

  await assert.rejects(
    () => client("/recommend/advisor", { method: "POST" }),
    (error) => {
      assert.equal(error.status, 400);
      assert.equal(error.message, guardrailMessage);
      return true;
    },
  );
});
test("Malformed model data is rejected; empty recommendations are valid", async () => {
  const api = createHttpPusulaApi({
    fetchImpl: async () => Response.json({ ...analysis, confidence: 999 }),
  });
  await assert.rejects(
    () => api.analyzeIdea({ text: "test", format: "image" }),
    (error) => error.code === "INVALID_RESPONSE",
  );
  assert.deepEqual(
    validate("recommendations", {
      confidence: "low",
      confidenceLabel: "Düşük",
      updatedAt: new Date().toISOString(),
      activeTopic: "Teknoloji",
      coldStart: true,
      timezoneBasis: "user_timezone",
      explanation: "Test",
      slots: [],
    }).slots,
    [],
  );
});
test("Invalid input is blocked before network access", () => {
  const api = createHttpPusulaApi({
    fetchImpl: () => {
      throw new Error("must not fetch");
    },
  });
  assert.throws(
    () => api.analyzeIdea({ text: " ", format: "video" }),
    (error) => error.code === "VALIDATION",
  );
  assert.throws(() =>
    api.analyzeIdea({ text: "x".repeat(501), format: "video" }),
  );
});
test("Timeout and caller cancellation remain distinguishable", async () => {
  const pending = (_url, { signal }) =>
    new Promise((resolve, reject) => {
      if (signal.aborted) reject(new DOMException("Aborted", "AbortError"));
      else
        signal.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
    });
  await assert.rejects(
    () => createApiClient({ fetchImpl: pending, timeoutMs: 5 })("/test"),
    (error) => error.code === "TIMEOUT",
  );
  const controller = new AbortController();
  const request = createApiClient({ fetchImpl: pending })("/test", {
    signal: controller.signal,
  });
  controller.abort();
  await assert.rejects(
    () => request,
    (error) => error.name === "AbortError",
  );
});
test("Mock job progress comes from job state and slots carry future ISO timestamps", async () => {
  let now = Date.parse("2026-09-14T00:00:00Z");
  const api = createMockPusulaApi({ latency: 0, now: () => now });
  const job = await api.startPreparation(
    { interests: ["teknoloji", "yazilim"] },
    { requestId: "job-1" },
  );
  assert.equal(job.progress, 0);
  now += 3000;
  assert.equal((await api.getPreparation(job.id)).status, "completed");
  const data = await api.getRecommendations();
  assert.equal(data.slots.length, 3);
  assert.ok(data.slots.every((slot) => Date.parse(slot.startsAt) > now));
});
// Captured verbatim from POST /api/recommend/advisor on the running stack.
const advisorPayload = {
  request_id: "req-396ae5a8",
  topic: "Yapay Zeka",
  primary_category: "technology",
  primary_category_confidence: 0.65,
  primary_category_is_fallback: false,
  text_category: "technology",
  category_source: "text",
  windows: [
    {
      window_start_local: "2026-09-17T15:00:00+03:00",
      window_end_local: "2026-09-17T18:00:00+03:00",
      window_start_utc: "2026-09-17T12:00:00Z",
      window_end_utc: "2026-09-17T15:00:00Z",
      weekday: "Perşembe",
      weekday_index: 3,
      bucket: 5,
      time_range_local: "15.00–18.00",
      base_potential: 6.196,
      observational_time_lift: 0.0424,
      relative_potential: 0.1578,
      confidence: "low",
      confidence_label: "Düşük",
      support_post_count: 2687,
      support_user_count: 695,
      evidence_level: "global_weekday_bucket",
      lift_ci_low: -0.19858,
      lift_ci_high: 0.263861,
      is_tie_or_broad_window: true,
      timezone_basis: "user_timezone",
    },
  ],
  accepted_tags: ["#yapayzeka"],
  rejected_tags: [],
  unknown_tags: [],
  suggested_tags: ["#yapayzeka", "#ai", "#derinogrenme"],
  explanation: "Bu içerik için saat etkisi belirgin değil.",
  similar_posts: [
    {
      post_id: "237695",
      title: "t",
      hour: 12,
      weekday: 0,
      popularity_score: 8.5,
      similarity: 0.1614,
      tags: ["technology"],
    },
  ],
  history_depth: "cold_start",
  confidence_level: "low",
  confidence: "low",
  is_tie_or_broad_window: true,
  timezone_basis: "user_timezone",
  timezone_fallback: false,
  model_version: "base-potential-lgbm + time-lift-table + gemma",
  data_source: "SMPD benchmark (observational) & NSosyal demo",
  service_mode: "deep_advisor",
  media_analysis: null,
};
test("Advisor payload maps onto the contract without inventing units", () => {
  const result = validate("analysis", toAnalysis(advisorPayload));
  assert.equal(result.id, "req-396ae5a8");
  assert.equal(result.tip, advisorPayload.explanation);
  assert.deepEqual(result.hashtags, ["yapayzeka", "ai", "derinogrenme"]);
  assert.equal(result.bestTime, "Perşembe 15.00–18.00");
  assert.equal(result.confidenceLabel, "Düşük");
  assert.equal(result.categorySource, "text");
  assert.equal(result.textCategory, "technology");
  assert.equal(result.mediaAnalysis, null);
  // Score-unit residuals survive untouched, signs included.
  assert.equal(result.windows[0].observationalTimeLift, 0.0424);
  assert.equal(result.windows[0].relativePotential, 0.1578);
  assert.equal(result.windows[0].liftCiLow, -0.19858);
  // The bar is a rank across the returned set; a lone window sits in the middle.
  assert.equal(result.windows[0].rankPercent, 50);
});
test("Negative relative potential is preserved, never clamped to zero", () => {
  const payload = {
    ...advisorPayload,
    windows: [
      { ...advisorPayload.windows[0], relative_potential: -0.31, bucket: 1 },
      { ...advisorPayload.windows[0], relative_potential: 0.12, bucket: 2 },
    ],
  };
  const { windows } = toAnalysis(payload);
  assert.equal(windows[0].relativePotential, -0.31);
  assert.equal(windows[0].rankPercent, 0);
  assert.equal(windows[1].rankPercent, 100);
});
test("An empty window list still yields a valid analysis", () => {
  const { windows, bestTime } = toAnalysis({ ...advisorPayload, windows: [] });
  assert.deepEqual(windows, []);
  assert.equal(bestTime, "Uygun pencere bulunamadı");
});
test("Quick payload maps onto recommendations", () => {
  const result = validate(
    "recommendations",
    toRecommendations(
      {
        user_id: "u",
        active_topic: "Teknoloji",
        windows: [advisorPayload.windows[0]],
        cold_start: true,
        confidence: "low",
        confidence_label: "Düşük",
        timezone_basis: "user_timezone",
        explanation: "x",
      },
      { receivedAt: "2026-09-13T16:00:00Z" },
    ),
  );
  assert.equal(result.activeTopic, "Teknoloji");
  assert.equal(result.updatedAt, "2026-09-13T16:00:00Z");
  assert.equal(result.slots[0].day, "Perşembe");
});
test("Interest ids map onto the canonical vocabulary, dedupe, and stay in it", () => {
  assert.deepEqual(mapInterests(["teknoloji", "araba"]), ["Teknoloji Trendleri"]);
  assert.deepEqual(mapInterests(["yapayzekâ", "yazilim"]), [
    "Yapay Zeka",
    "Yazılım",
  ]);
  assert.deepEqual(mapInterests(["bilinmeyen"]), []);
  // Mirrors backend/services/profile.py::TOPIC_SEEDS; drift fails here first.
  const backendTopics = [
    "Yapay Zeka",
    "Yazılım",
    "Teknoloji Trendleri",
    "Oyun",
    "Eğitim",
    "Finans",
    "Spor",
    "Kültür-Sanat",
    "Girişimcilik",
    "Yaşam",
  ];
  for (const topic of TOPIC_VOCABULARY)
    assert.ok(backendTopics.includes(topic), `${topic} is not a backend topic`);
});
// Captured from POST /api/media/analyze on the running stack.
const mediaPayload = {
  media_id: "abc123",
  media_kind: "photo",
  filename: "yemek.jpg",
  content_type: "image/jpeg",
  size_bytes: 2048,
  frames_analyzed: 1,
  duration_seconds: null,
  width: 800,
  height: 600,
  topic: "Yaşam",
  topic_confidence: 0.5014,
  canonical_category: "food_dining",
  category_confidence: 0.5721,
  category_margin: 0.4242,
  suggested_tags: ["#yemek", "#sağlık"],
  uncertain: false,
  model_name: "openai/clip-vit-base-patch32",
  embedding_dim: 512,
};
test("FormData reaches fetch untouched so the browser sets the boundary", async () => {
  const form = new FormData();
  form.append("file", new Blob(["x"], { type: "image/png" }), "x.png");
  let captured;
  await createApiClient({
    baseUrl: "/api",
    fetchImpl: async (url, options) => {
      captured = { url, options };
      return Response.json({ ok: true });
    },
  })("/media/analyze", { method: "POST", body: form });
  assert.equal(captured.url, "/api/media/analyze");
  // Passing the FormData through unchanged is the whole point: only the browser
  // knows the multipart boundary, so Content-Type must stay unset.
  assert.equal(captured.options.body, form);
  assert.equal(captured.options.headers["Content-Type"], undefined);
});
test("A confident image owns the category while the text proposal is kept", () => {
  const result = validate(
    "analysis",
    toAnalysis({
      ...advisorPayload,
      primary_category: "food_dining",
      primary_category_confidence: 0.5721,
      primary_category_is_fallback: false,
      text_category: "technology",
      category_source: "media",
      media_analysis: mediaPayload,
    }),
  );
  assert.equal(result.categorySource, "media");
  assert.equal(result.primaryCategory, "food_dining");
  // Kept so the UI can report the disagreement the image overruled.
  assert.equal(result.textCategory, "technology");
  assert.equal(result.mediaAnalysis.canonicalCategory, "food_dining");
  assert.equal(result.mediaAnalysis.mediaId, "abc123");
});
test("An uncertain image keeps null labels instead of guessing", () => {
  const result = validate(
    "mediaAnalysis",
    toMediaAnalysis({
      ...mediaPayload,
      topic: null,
      canonical_category: null,
      suggested_tags: [],
      uncertain: true,
    }),
  );
  assert.equal(result.topic, null);
  assert.equal(result.canonicalCategory, null);
  assert.deepEqual(result.suggestedTags, []);
  assert.equal(result.uncertain, true);
});
test("Mock media path mirrors the backend rule, uncertain images included", async () => {
  const api = createMockPusulaApi({ latency: 0 });
  const media = await api.analyzeMedia({ name: "yemek.jpg", size: 1024 });
  assert.equal(media.canonicalCategory, "food_dining");
  const adopted = await api.analyzeIdea({
    text: "bugün ne paylaşsam",
    format: "image",
    mediaId: media.mediaId,
  });
  assert.equal(adopted.categorySource, "media");
  assert.equal(adopted.primaryCategory, "food_dining");

  // A file the model cannot label must leave the text category in charge.
  const blurry = await api.analyzeMedia({ name: "belirsiz.jpg", size: 1024 });
  assert.equal(blurry.uncertain, true);
  const fallback = await api.analyzeIdea({
    text: "bugün ne paylaşsam",
    format: "image",
    mediaId: blurry.mediaId,
  });
  assert.equal(fallback.categorySource, "text");
  assert.equal(fallback.primaryCategory, "technology");
});

test("Sample users map onto the contract without inventing a depth", () => {
  assert.deepEqual(
    toSampleUsers({
      users: [
        { user_id: "31253@N15", post_count: 1376, history_depth: "high_history" },
      ],
    }),
    [{ userId: "31253@N15", postCount: 1376, historyDepth: "high_history" }],
  );
  assert.deepEqual(toSampleUsers({}), []);
  // A depth outside the backend vocabulary must fail loudly, not render as a code.
  assert.throws(() => validate("sampleUsers", [{ userId: "x", postCount: 1, historyDepth: "rich" }]));
});

test("Choosing an account persists the id and the adapter picks it up per request", async () => {
  const previous = globalThis.localStorage;
  const store = new Map();
  globalThis.localStorage = {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
  };
  try {
    setUserId("31253@N15");
    assert.equal(resolveUserId(), "31253@N15");

    const seen = [];
    const api = createBackendPusulaApi({
      userId: null,
      timeZone: "Europe/Istanbul",
      fetchImpl: async (url, options) => {
        seen.push(options?.body ? JSON.parse(options.body).user_id : url);
        return Response.json({
          request_id: "r",
          model_version: "test",
          topic: "Yaşam",
          primary_category: "food_dining",
          primary_category_confidence: 0.9,
          text_category: "food_dining",
          category_source: "text",
          media_analysis: null,
          confidence: "high",
          history_depth: "high_history",
          is_tie_or_broad_window: false,
          timezone_basis: "user_offset",
          suggested_tags: ["#food"],
          explanation: "Gözlemsel bir öneri.",
          windows: [
            {
              weekday: "Pazartesi",
              weekday_index: 0,
              bucket: 5,
              time_range_local: "15.00–18.00",
              window_start_utc: "2026-09-14T12:00:00Z",
              relative_potential: 0.4,
              support_post_count: 100,
              support_user_count: 50,
              observational_time_lift: 0.4159,
              lift_ci_low: 0.1,
              lift_ci_high: 0.7,
              confidence: "high",
              confidence_label: "Yüksek",
              evidence_level: "category_weekday_bucket",
            },
          ],
          similar_posts: [],
        });
      },
    });

    await api.analyzeIdea({ text: "bir fikir", format: "image" });
    // Switching accounts must change the *next* request. A value captured at
    // construction would keep sending the previous account forever.
    setUserId("21102@N64");
    await api.analyzeIdea({ text: "bir fikir", format: "image" });

    assert.deepEqual(seen, ["31253@N15", "21102@N64"]);
  } finally {
    globalThis.localStorage = previous;
  }
});

test("An explicitly injected user id still pins the adapter", () => {
  assert.equal(resolveUserId({ getItem: () => "local-account" }), "local-account");
  assert.equal(setUserId("pinned", { setItem: () => {} }), "pinned");
});
