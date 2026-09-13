import test from "node:test";
import assert from "node:assert/strict";
import { createApiClient } from "../src/services/apiClient.js";
import { createHttpPusulaApi } from "../src/services/pusula/httpAdapter.js";
import { createMockPusulaApi } from "../src/services/pusula/mockAdapter.js";
import {
  mapInterests,
  toAnalysis,
  toRecommendations,
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
