import { validate, validateAnalysisInput } from "./contracts.js";
export function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, ms);
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
  });
}
function store(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* Optional demo persistence. */
  }
}
/** @returns {import('./types').PusulaApi} */
export function createMockPusulaApi({
  latency = 300,
  now = () => Date.now(),
} = {}) {
  const jobs = new Map();
  const respond = async (kind, value, { signal } = {}) => {
    await delay(latency, signal);
    return validate(kind, value);
  };
  // Mirrors the backend window contract field-for-field, so the mock and http
  // adapters stay interchangeable and the views render either one unchanged.
  const buildSlots = () =>
    [
      {
        id: "slot-1",
        day: "Salı",
        time: "20.00–23.00",
        // Score-unit residuals, mirroring the backend's own scale.
        relativePotential: 0.16,
        rankPercent: 100,
        supportPostCount: 2615,
        supportUserCount: 739,
        observationalTimeLift: 0.0412,
        liftCiLow: -0.081,
        liftCiHigh: 0.164,
        confidence: "medium",
        confidenceLabel: "Orta",
        evidenceLevel: "category_weekday_bucket",
      },
      {
        id: "slot-2",
        day: "Perşembe",
        time: "19.00–22.00",
        relativePotential: 0.06,
        rankPercent: 50,
        supportPostCount: 1800,
        supportUserCount: 625,
        observationalTimeLift: 0.0188,
        liftCiLow: -0.121,
        liftCiHigh: 0.103,
        confidence: "medium",
        confidenceLabel: "Orta",
        evidenceLevel: "category_weekday_bucket",
      },
      {
        id: "slot-3",
        day: "Cumartesi",
        time: "14.00–17.00",
        relativePotential: -0.04,
        rankPercent: 0,
        supportPostCount: 1402,
        supportUserCount: 508,
        observationalTimeLift: 0.0071,
        liftCiLow: -0.142,
        liftCiHigh: 0.091,
        confidence: "low",
        confidenceLabel: "Düşük",
        evidenceLevel: "global_weekday_bucket",
      },
    ].map((slot, index) => {
      const date = new Date(now());
      const desired = [2, 4, 6][index];
      const today = new Date(now() + 3 * 3600000).getUTCDay();
      const offset = (desired - today + 7) % 7;
      const hours = Number(slot.time.slice(0, 2));
      date.setUTCDate(date.getUTCDate() + offset);
      // Istanbul is UTC+3; the window starts at the local hour shown.
      date.setUTCHours(hours - 3, 0, 0, 0);
      if (date.getTime() <= now()) date.setUTCDate(date.getUTCDate() + 7);
      return {
        ...slot,
        startsAt: date.toISOString(),
        timeZone: "Europe/Istanbul",
      };
    });
  const recommendations = () => ({
    confidence: "medium",
    confidenceLabel: "Orta",
    updatedAt: new Date(now()).toISOString(),
    activeTopic: "Teknoloji",
    coldStart: false,
    timezoneBasis: "user_timezone",
    explanation:
      "Örnek veri: seçili konularda akşam saatleri daha yüksek etkileşim gösteriyor. Gerçek açıklama backend'den gelir.",
    slots: buildSlots(),
  });
  return {
    mode: "mock",
    async saveProfile(body, options) {
      const value = await respond("profile", body, options);
      store("npusula-interests", value.interests);
      return value;
    },
    async startPreparation(body, options) {
      const id = options?.requestId || crypto.randomUUID();
      if (!jobs.has(id)) jobs.set(id, now());
      return respond(
        "job",
        {
          id,
          status: "queued",
          progress: 0,
          message: "Örnek profil hazırlanıyor",
        },
        options,
      );
    },
    getPreparation(id, options) {
      if (!jobs.has(id)) throw new Error("Hazırlık işi bulunamadı.");
      const progress = Math.min(100, Math.floor((now() - jobs.get(id)) / 30));
      return respond(
        "job",
        {
          id,
          status: progress === 100 ? "completed" : "running",
          progress,
          message:
            progress === 100
              ? "Örnek rota hazır"
              : "Profil ve kitle sinyalleri hazırlanıyor",
        },
        options,
      );
    },
    getRecommendations: (options) =>
      respond("recommendations", recommendations(), options),
    analyzeIdea(body, options) {
      validateAnalysisInput(body);
      return respond(
        "analysis",
        {
          id: crypto.randomUUID(),
          modelVersion: "Demo",
          topic: "Yapay Zeka",
          primaryCategory: "technology",
          primaryCategoryConfidence: 0.65,
          confidence: "medium",
          confidenceLabel: "Orta",
          bestTime: "Salı 20.00–23.00",
          alternativeTime: "Perşembe 19.00–22.00",
          hashtags: [
            "YapayZeka",
            "Teknoloji",
            "Yazılım",
            "Gelecek",
            "ÜretkenYapayZeka",
          ],
          tip: "İlk 3 saniyede ana fikri gösterin. İzleyiciye bir soru sorarak yorum etkileşimini destekleyin.",
          historyDepth: "cold_start",
          isTieOrBroadWindow: true,
          timezoneBasis: "user_timezone",
          windows: buildSlots(),
          similarPosts: [
            {
              postId: "237695",
              title: "Örnek benzer gönderi başlığı",
              weekdayIndex: 2,
              hour: 20,
              popularityScore: 8.5,
              similarity: 0.16,
              tags: ["technology"],
            },
          ],
        },
        options,
      );
    },
    async createPlan(body, options) {
      const value = await respond(
        "plan",
        {
          id: options?.requestId || crypto.randomUUID(),
          slotId: body.slotId,
          startsAt: body.startsAt,
          status: "saved",
        },
        options,
      );
      store("npusula-last-plan", value);
      return value;
    },
    async saveDraft(body, options) {
      validateAnalysisInput(body);
      const value = await respond(
        "draft",
        { id: options?.requestId || crypto.randomUUID(), ...body },
        options,
      );
      store("npusula-draft", body.text);
      return value;
    },
  };
}
