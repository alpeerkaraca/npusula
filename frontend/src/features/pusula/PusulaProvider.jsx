import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  pusulaApi,
  mintUserId,
  resolveUserId,
  setUserId as persistUserId,
} from "../../services/pusula/index.js";
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
  const [format, setFormatState] = useState("video");
  function setFormat(nextFormat) {
    setFormatState(nextFormat);
    if (nextFormat === "thread" && media) {
      setMedia(null);
      mediaTask.reset();
    } else if (nextFormat === "image" && media?.mediaKind === "video") {
      setMedia(null);
      mediaTask.reset();
    } else if (nextFormat === "video" && media?.mediaKind === "photo") {
      setMedia(null);
      mediaTask.reset();
    }
  }
  const [job, setJob] = useState(null);
  const [notice, setNotice] = useState("");
  const [plans, setPlans] = useState([]);
  // The analysed upload, provider-local like `format`. Kept separate from
  // `draft` so the composer still receives exactly what the user typed.
  const [media, setMedia] = useState(null);
  // The account every request is made for. localStorage is the source of truth
  // (the adapter re-reads it per request); this copy exists so the picker can
  // show the current choice and so switching can drop the previous account's
  // cached answers.
  const [userId, setUserIdState] = useState(resolveUserId);
  const preparation = useApiTask(),
    recommendations = useApiTask(),
    analysis = useApiTask(),
    mediaTask = useApiTask(),
    sampleUsers = useApiTask(),
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
  }, [draft, format, media, analysis.reset]);
  useEffect(() => {
    mutation.reset();
  }, [activePage, draft, format, media, mutation.reset]);
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
  useEffect(() => {
    sampleUsers.run((signal) => api.listSampleUsers({ signal }));
    return sampleUsers.cancel;
  }, [api, sampleUsers.run, sampleUsers.cancel]);
  /**
   * Switches the active account. Persisting the id is what actually changes who
   * the next request is for; the resets below drop answers that described the
   * previous account and would otherwise stay on screen as if they still held.
   */
  function chooseUser(nextUserId) {
    if (!nextUserId || nextUserId === userId) return;
    persistUserId(nextUserId);
    setUserIdState(nextUserId);
    analysis.reset();
    recommendations.reset();
    preparation.reset();
    mediaTask.reset();
    mutation.reset();
    setMedia(null);
    setPlans([]);
    setJob(null);
    setNotice(`Hesap değiştirildi: ${nextUserId}`);
  }
  function chooseNewUser() {
    chooseUser(mintUserId());
  }
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
        setJob({ id: "prep-init", status: "running", progress: 15, message: "Kategori sinyalleri işleniyor..." });
        await api.saveProfile({ interests }, { signal });
        prepareKey.current ||= newId();
        current = await api.startPreparation(
          { interests },
          { signal, requestId: prepareKey.current },
        );
      }
      for (let attempt = 0; attempt < 300; attempt++) {
        if (signal.aborted) throw new DOMException("Aborted", "AbortError");
        if (current.status === "failed") {
          setJob(current);
          throw new Error(current.message || "Hazırlık tamamlanamadı.");
        }
        if (current.status === "completed") {
          setJob({ ...current, progress: 40, message: "Kategori ağırlıkları indekslendi" });
          await delay(300, signal);
          setJob({ ...current, progress: 75, message: "Kitle etkileşim dalgaları analiz edildi" });
          await delay(400, signal);
          setJob({ ...current, progress: 100, message: "Profil ve rota hazır" });
          return current;
        }
        setJob(current);
        await delay(800, signal);
        current = await api.getPreparation(current.id, { signal });
      }
      throw new Error(
        "Hazırlık beklenenden uzun sürdü. Yeniden kontrol edebilirsiniz.",
      );
    });
  }
  async function uploadMedia(file) {
    const result = await mediaTask.run((signal) =>
      api.analyzeMedia(file, { signal, requestId: newId() }),
    );
    // An aborted run resolves to undefined; the previous analysis stays put.
    if (result) setMedia(result);
  }
  function clearMedia() {
    mediaTask.reset();
    setMedia(null);
  }
  async function analyze() {
    const text = draft.trim();
    if (!text || text.length > 500)
      return setNotice("1–500 karakter arasında bir fikir yazın.");
    await analysis.run((signal) =>
      api.analyzeIdea(
        {
          text,
          format,
          interests,
          // Present only when an upload was analysed; it then owns the category.
          ...(media ? { mediaId: media.mediaId } : {}),
        },
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
    userId,
    chooseUser,
    chooseNewUser,
    // Empty until the backend answers; the picker still offers "new account".
    sampleUsers: sampleUsers.data || [],
    interests,
    toggleInterest,
    format,
    setFormat,
    media,
    mediaTask,
    uploadMedia,
    clearMedia,
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
