import React from "react";
import { usePusula } from "../PusulaProvider.jsx";
import DesignIcon from "../DesignIcon.jsx";
import RequestState from "../RequestState.jsx";
import AnalysisResult from "../components/AnalysisResult.jsx";
import MediaUpload from "../components/MediaUpload.jsx";
import { useAnalysisStage } from "../useAnalysisStage.js";
export default function IdeasView() {
  const ui = usePusula();
  const stage = useAnalysisStage(ui.analysis.status === "loading");
  return (
    <div className="pusula-view">
      <header className="flex justify-between gap-space-md pb-space-md mb-space-lg">
        <div className="flex items-center gap-space-md">
          <button
            className="bg-surface-container-low rounded-lg px-2 py-1 text-label-md"
            onClick={() => ui.navigate("assistant")}
          >
            <DesignIcon name="arrow_back" /> Ana Ekrana Dön
          </button>
          <h1 className="text-headline-sm font-bold">
            <DesignIcon name="explore" className="text-primary" /> N-Pusula
            İçerik Fikri Danışmanı
          </h1>
        </div>
        <span className="text-code-sm text-tertiary self-start bg-surface-container-high rounded-full px-3 py-1">
          {ui.mode === "mock"
            ? "Demo"
            : ui.analysis.data?.modelVersion || "Model servisi"}
        </span>
      </header>
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg items-start">
        <div className="xl:col-span-5 flex flex-col gap-space-lg">
          <section className="p-space-lg rounded-xl bg-surface-container-low shadow-xl">
            <header className="flex justify-between pb-space-md">
              <strong className="text-title-sm">
                <DesignIcon name="auto_awesome" className="text-primary" /> 1.
                İçerik Parametreleri
              </strong>
              <small className="text-on-surface-variant">GİRDİ</small>
            </header>
            <label className="text-label-sm text-on-surface-variant">
              FORMAT TÜRÜ
            </label>
            <div
              className="grid grid-cols-3 gap-2 mt-space-xs mb-space-lg"
              id="format-selector"
            >
              {[
                ["video", "Video", "videocam"],
                ["image", "Görsel / Post", "image"],
                ["thread", "Thread", "notes"],
              ].map(([value, label, icon]) => {
                const isSelected = ui.format === value;
                return (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => ui.setFormat(value)}
                    className={`rounded-xl py-2.5 px-2 text-label-md font-semibold transition-all duration-200 border flex items-center justify-center gap-1.5 ${
                      isSelected
                        ? "bg-[#06334c] text-[#98cbff] border-[#00a3ff] shadow-[0_0_12px_rgba(0,163,255,0.25)]"
                        : "bg-surface-container-high text-on-surface-variant hover:bg-surface-container-highest hover:text-on-surface border-transparent"
                    }`}
                  >
                    <DesignIcon
                      name={icon}
                      className={isSelected ? "text-primary" : "text-on-surface-variant"}
                    />{" "}
                    {label}
                  </button>
                );
              })}
            </div>
            <div className="flex justify-between text-label-sm mb-space-xs">
              <label htmlFor="prompt-input">İÇERİK VE SENARYO AÇIKLAMASI</label>
              <span className="text-primary">{ui.draft.length} / 500</span>
            </div>
            <textarea
              id="prompt-input"
              value={ui.draft}
              onChange={(event) => ui.setDraft(event.target.value)}
              maxLength={500}
              rows={6}
              placeholder="İçerik fikrinizi anlatın..."
              className="w-full p-space-md bg-surface-container-lowest rounded-xl text-body-md text-on-surface resize-none"
            />
            <button
              disabled={!ui.draft.trim() || ui.analysis.status === "loading"}
              onClick={ui.analyze}
              className="w-full mt-space-lg pusula-primary"
            >
              <DesignIcon name="auto_awesome" />{" "}
              {ui.analysis.status === "loading"
                ? "Analiz ediliyor…"
                : "Fikri Analiz Et"}
            </button>
            <button
              onClick={() => ui.navigate("setup")}
              className="mt-space-md w-full text-body-sm text-on-surface-variant bg-surface-container rounded-xl p-space-sm"
            >
              <DesignIcon name="tune" /> Hedef Kitle / Odak Alanlarını Değiştir
            </button>
          </section>
          <MediaUpload />
        </div>
        <div className="xl:col-span-7">
          <RequestState
            task={ui.analysis}
            retry={ui.analyze}
            loading={stage || undefined}
            empty="Fikrinizi yazıp analiz başlattığınızda değerlendirme burada görünecek."
          >
            {ui.analysis.data && (
              <AnalysisResult
                result={ui.analysis.data}
                onCopy={ui.copyAnalysis}
                onNew={() => ui.setDraft("")}
                onDraft={ui.openDraft}
                busy={ui.mutation.status === "loading"}
              />
            )}
          </RequestState>
        </div>
      </div>
    </div>
  );
}
