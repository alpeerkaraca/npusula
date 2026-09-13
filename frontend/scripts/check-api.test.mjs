import test from "node:test";
import assert from "node:assert/strict";
import { createApiClient } from "../src/services/apiClient.js";
import { createHttpPusulaApi } from "../src/services/pusula/httpAdapter.js";
import { createMockPusulaApi } from "../src/services/pusula/mockAdapter.js";
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
      confidence: 0,
      updatedAt: new Date().toISOString(),
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
