import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { pusulaApi } from "../../services/pusula/index.js";
import { delay } from "../../services/pusula/mockAdapter.js";
import { useApiTask } from "../../hooks/useApiTask.js";
const Context = createContext(null);
function initialInterests() {
  try {
    const value = JSON.parse(localStorage.getItem("npusula-interests"));
    return Array.isArray(value) &&
      value.every((item) => typeof item === "string")
      ? value.slice(0, 5)
      : ["teknoloji", "yazilim", "yapayzekâ"];
  } catch {
    return ["teknoloji", "yazilim", "yapayzekâ"];
  }
}
const newId = () =>
  globalThis.crypto?.randomUUID?.() ||
  `request-${Date.now()}-${Math.random().toString(36).slice(2)}`;
export function PusulaProvider({
  children,
  navigate,
  draft,
  setDraft,
  activePage,
  api = pusulaApi,
}) {
  const [interests, setInterests] = useState(initialInterests);
  const [format, setFormat] = useState("video");
  const [job, setJob] = useState(null);
  const [notice, setNotice] = useState("");
  const [plans, setPlans] = useState([]);
  const preparation = useApiTask(),
    recommendations = useApiTask(),
    analysis = useApiTask(),
    mutation = useApiTask();
  const prepareKey = useRef(null);
  const mutationKeys = useRef(new Map());
  const requestKey = (payload) => {
    const key = JSON.stringify(payload);
    if (!mutationKeys.current.has(key)) mutationKeys.current.set(key, newId());
    return mutationKeys.current.get(key);
  };
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    analysis.reset();
  }, [draft, format, analysis.reset]);
  useEffect(() => {
    mutation.reset();
  }, [activePage, draft, format, mutation.reset]);
  useEffect(() => {
    if (activePage !== "ideas") analysis.reset();
  }, [activePage, analysis.reset]);
  useEffect(() => {
    if (activePage !== "assistant") return;
    recommendations.run((signal) => api.getRecommendations({ signal }));
    return recommendations.cancel;
  }, [activePage, api, recommendations.run, recommendations.cancel]);
  useEffect(() => {
    if (activePage !== "preparing") preparation.reset();
  }, [activePage, preparation.reset]);
  function toggleInterest(value) {
    if (!interests.includes(value) && interests.length >= 5)
      return setNotice("En fazla 5 odak alanı seçebilirsiniz.");
    setInterests((values) =>
      values.includes(value)
        ? values.filter((item) => item !== value)
        : [...values, value],
    );
    setJob(null);
    prepareKey.current = null;
  }
  async function prepare() {
    if (interests.length < 2) return setNotice("En az 2 odak alanı seçin.");
    navigate("preparing");
    await preparation.run(async (signal) => {
      let current = job;
      if (!current || current.status === "failed") {
        if (current?.status === "failed") prepareKey.current = null;
        await api.saveProfile({ interests }, { signal });
        prepareKey.current ||= newId();
        current = await api.startPreparation(
          { interests },
          { signal, requestId: prepareKey.current },
        );
      }
      for (let attempt = 0; attempt < 300; attempt++) {
        if (signal.aborted) throw new DOMException("Aborted", "AbortError");
        setJob(current);
        if (current.status === "failed")
          throw new Error(current.message || "Hazırlık tamamlanamadı.");
        if (current.status === "completed") return current;
        await delay(1000, signal);
        current = await api.getPreparation(current.id, { signal });
      }
      throw new Error(
        "Hazırlık beklenenden uzun sürdü. Yeniden kontrol edebilirsiniz.",
      );
    });
  }
  async function analyze() {
    const text = draft.trim();
    if (!text || text.length > 500)
      return setNotice("1–500 karakter arasında bir fikir yazın.");
    await analysis.run((signal) =>
      api.analyzeIdea(
        { text, format, interests },
        { signal, requestId: newId() },
      ),
    );
  }
  async function plan(slot) {
    if (!slot) return;
    const payload = {
      slotId: slot.id,
      startsAt: slot.startsAt,
      timeZone: slot.timeZone,
      text: draft,
      format,
    };
    const result = await mutation.run((signal) =>
      api.createPlan(payload, { signal, requestId: requestKey(payload) }),
    );
    if (result) {
      setPlans((values) => [
        ...values.filter((item) => item.id !== result.id),
        result,
      ]);
      setNotice(
        api.mode === "mock"
          ? "Örnek plan kaydedildi; yayın veya bildirim oluşturulmadı."
          : "Plan sunucuya kaydedildi.",
      );
    }
  }
  async function openDraft() {
    // The backend does not generate draft copy, so the user's own idea text is
    // carried into the composer rather than a synthesised "AI draft".
    const text = draft.trim();
    if (!analysis.data || !text) return;
    const payload = { text, format };
    const result = await mutation.run((signal) =>
      api.saveDraft(payload, { signal, requestId: requestKey(payload) }),
    );
    if (result) {
      setDraft(result.text);
      navigate("home");
      setNotice("Fikriniz gönderi alanına aktarıldı.");
    }
  }
  async function copyAnalysis() {
    if (!analysis.data) return;
    try {
      await navigator.clipboard.writeText(
        `${draft.trim()}\n${analysis.data.hashtags.map((tag) => `#${tag}`).join(" ")}`,
      );
      setNotice("Öneriler kopyalandı.");
    } catch {
      setNotice("Panoya erişilemedi. Metni seçip kopyalayabilirsiniz.");
    }
  }
  const ui = {
    reloadRecommendations: () =>
      recommendations.run((signal) => api.getRecommendations({ signal })),
    mode: api.mode,
    interests,
    toggleInterest,
    format,
    setFormat,
    draft,
    setDraft,
    job,
    progress: job?.progress || 0,
    preparation,
    recommendations,
    analysis,
    mutation,
    plans,
    prepare,
    analyze,
    plan,
    openDraft,
    copyAnalysis,
    navigate,
    notify: setNotice,
  };
  return (
    <Context.Provider value={ui}>
      {children}
      {notice && (
        <div className="pusula-notice" role="status">
          {notice}
          <button aria-label="Bildirimi kapat" onClick={() => setNotice("")}>
            ×
          </button>
        </div>
      )}
    </Context.Provider>
  );
}
export function usePusula() {
  const value = useContext(Context);
  if (!value) throw new Error("PusulaProvider is required");
  return value;
}
