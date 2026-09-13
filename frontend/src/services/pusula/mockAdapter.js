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
  const recommendations = () => ({
    confidence: 94,
    updatedAt: new Date(now()).toISOString(),
    slots: [
      {
        id: "slot-1",
        day: "Salı",
        time: "20:30",
        onlinePercent: 85,
        reach: 45000,
        format: "Kısa Video / Medya Gönderisi",
        label: "En Yüksek Etkileşim (Peak Slot)",
      },
      {
        id: "slot-2",
        day: "Perşembe",
        time: "19:00",
        onlinePercent: 72,
        reach: 32000,
        format: "Bilgi Seli / Görsel",
        label: "İkincil Zirve (Yüksek Paylaşım Hızı)",
      },
      {
        id: "slot-3",
        day: "Cumartesi",
        time: "14:30",
        onlinePercent: 68,
        reach: 28500,
        format: "İnteraktif Tartışma",
        label: "Hafta Sonu Keşif Penceresi",
      },
    ].map((slot, index) => {
      const date = new Date(now());
      const desired = [2, 4, 6][index];
      const today = new Date(now() + 3 * 3600000).getUTCDay();
      let offset = (desired - today + 7) % 7;
      const [hours, minutes] = slot.time.split(":").map(Number);
      date.setUTCDate(date.getUTCDate() + offset);
      date.setUTCHours(hours - 3, minutes, 0, 0);
      if (date.getTime() <= now()) date.setUTCDate(date.getUTCDate() + 7);
      return {
        ...slot,
        startsAt: date.toISOString(),
        timeZone: "Europe/Istanbul",
      };
    }),
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
          confidence: 88,
          reachMin: 34500,
          reachMax: 52000,
          saveMultiplier: 4.8,
          commentProbability: 76,
          liftPercent: 38,
          bestTime: "Cuma 21:00",
          alternativeTime: "Cumartesi 11:30–13:00",
          hashtags: [
            "YapayZeka",
            "Teknoloji",
            "Yazılım",
            "Gelecek",
            "ÜretkenYapayZeka",
          ],
          tip: "İlk 3 saniyede ana fikri gösterin. İzleyiciye bir soru sorarak yorum etkileşimini destekleyin.",
          draft: body.text.trim(),
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
