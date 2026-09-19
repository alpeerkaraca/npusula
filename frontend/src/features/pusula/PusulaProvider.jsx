import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
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
function initialCreatedUsers() {
  try {
    const raw = localStorage.getItem("npusula-created-users");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveCreatedUserToStorage(user) {
  try {
    const raw = localStorage.getItem("npusula-created-users");
    const list = Array.isArray(JSON.parse(raw)) ? JSON.parse(raw) : [];
    if (!list.some((u) => u.userId === user.userId)) {
      list.unshift(user);
      localStorage.setItem("npusula-created-users", JSON.stringify(list.slice(0, 20)));
    }
  } catch {}
}

export function PusulaProvider({
  children,
  navigate,
  draft,
  setDraft,
  activePage,
  api = pusulaApi,
}) {
  const [createdUsers, setCreatedUsers] = useState(initialCreatedUsers);
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
  // Keep the last submitted analysis while the user edits the next idea.
  // Only an explicit analyze action replaces it; account/page changes reset it.
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
  }, [activePage, userId, api, recommendations.run, recommendations.cancel]);
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
    if (activePage === "assistant") {
      recommendations.run((signal) => api.getRecommendations({ signal }));
    }
  }
  function chooseNewUser() {
    const nextUserId = mintUserId();
    const newRecord = {
      userId: nextUserId,
      postCount: 0,
      historyDepth: "cold_start",
    };
    saveCreatedUserToStorage(newRecord);
    setCreatedUsers((prev) => [
      newRecord,
      ...prev.filter((u) => u.userId !== nextUserId),
    ]);
    chooseUser(nextUserId);
    const defaultInterests = ["teknoloji", "yazilim", "yapayzekâ"];
    setInterests(defaultInterests);
    try {
      localStorage.setItem("npusula-interests", JSON.stringify(defaultInterests));
    } catch {}
    api.saveProfile({ interests: defaultInterests }).catch(() => {});
    navigate("setup");
    setNotice(`Yeni hesap oluşturuldu: ${nextUserId}. Kurulum ekranındasınız.`);
  }
  async function saveProfile(customInterests = interests) {
    if (customInterests.length < 2) {
      setNotice("En az 2 odak alanı seçin.");
      return false;
    }
    const result = await mutation.run(async (signal) => {
      await api.saveProfile({ interests: customInterests }, { signal });
      try {
        localStorage.setItem(
          "npusula-interests",
          JSON.stringify(customInterests),
        );
      } catch {}
      return { interests: customInterests };
    });
    if (result) {
      setNotice("Hesap kurulumu ve tercihler kaydedildi.");
      return true;
    }
    return false;
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
        try {
          localStorage.setItem("npusula-interests", JSON.stringify(interests));
        } catch {}
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
  const reloadRecommendations = useCallback(
    () => recommendations.run((signal) => api.getRecommendations({ signal })),
    [recommendations, api],
  );

  const combinedUsers = useMemo(() => {
    const base = sampleUsers.data || [];
    const created = createdUsers || [];
    const map = new Map();
    for (const u of created) map.set(u.userId, u);
    for (const u of base) {
      if (!map.has(u.userId)) map.set(u.userId, u);
    }
    return Array.from(map.values());
  }, [sampleUsers.data, createdUsers]);

  const ui = useMemo(
    () => ({
      reloadRecommendations,
      mode: api.mode,
      userId,
      chooseUser,
      chooseNewUser,
      sampleUsers: combinedUsers,
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
      saveProfile,
      analyze,
      plan,
      openDraft,
      copyAnalysis,
      navigate,
      notify: setNotice,
    }),
    [
      reloadRecommendations,
      api,
      userId,
      chooseUser,
      chooseNewUser,
      combinedUsers,
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
      preparation,
      recommendations,
      analysis,
      mutation,
      plans,
      prepare,
      saveProfile,
      analyze,
      plan,
      openDraft,
      copyAnalysis,
      navigate,
      setNotice,
    ],
  );

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
