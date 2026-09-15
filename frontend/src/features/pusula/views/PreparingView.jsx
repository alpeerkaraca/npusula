import React from "react";
import { usePusula } from "../PusulaProvider.jsx";
import DesignIcon from "../DesignIcon.jsx";
export default function PreparingView() {
  const ui = usePusula();
  const isCompleted = ui.job?.status === "completed" || ui.progress >= 100;
  const step1Done = isCompleted || ui.progress >= 30;
  const step2Done = isCompleted || ui.progress >= 70;
  const step3Done = isCompleted || ui.progress >= 100;

  return (
    <div
      className="pusula-view"
      aria-busy={ui.preparation.status === "loading"}
    >
      <div className="flex flex-col w-full">
        <div className="relative w-full max-w-4xl mx-auto flex flex-col items-center justify-center py-space-xl overflow-hidden">
          <div className="absolute -top-16 left-1/2 -translate-x-1/2 w-96 h-96 rounded-full bg-gradient-to-br from-primary-container/20 via-secondary-container/10 to-transparent blur-3xl pointer-events-none -z-10"></div>
          <div className="absolute bottom-10 left-1/3 w-80 h-80 rounded-full bg-tertiary-container/10 blur-3xl pointer-events-none -z-10"></div>

          <div className="w-full bg-surface-container/70 backdrop-blur-2xl rounded-xl shadow-2xl p-space-xl flex flex-col items-center text-center relative overflow-hidden">
            <div className="w-full flex items-center justify-between pb-space-lg mb-space-md">
              <div className="flex items-center gap-space-sm">
                <span className={`inline-flex w-2.5 h-2.5 rounded-full ${isCompleted ? "bg-tertiary" : "bg-secondary-container animate-ping"}`}></span>
                <span className="font-code-sm text-code-sm uppercase tracking-widest text-secondary font-semibold">
                  {ui.mode === "mock" ? "NPusula Core // Örnek" : "NPusula Core"}
                </span>
              </div>
              <div className="flex items-center gap-space-xs font-code-sm text-code-sm text-on-surface-variant bg-surface-container-lowest/80 px-space-sm py-1 rounded-full">
                <DesignIcon name="hub" className=" text-[14px] text-tertiary" />
                <span>
                  {"Hazırlık: "}
                  <strong className={`font-semibold ${isCompleted ? "text-tertiary" : "text-on-surface"}`}>
                    {isCompleted ? "Tamamlandı" : "Sürüyor"}
                  </strong>
                </span>
              </div>
            </div>

            <div className="relative w-64 h-64 my-space-md flex items-center justify-center">
              <div className="absolute inset-0 rounded-full bg-transparent shadow-[0_0_50px_rgba(0,163,255,0.12)]"></div>

              <svg
                className={`absolute inset-0 w-full h-full ${isCompleted ? "opacity-40" : "animate-[spin_24s_linear_infinite]"}`}
                fill="none"
                viewBox="0 0 200 200"
              >
                <circle
                  className="text-primary"
                  cx="100"
                  cy="100"
                  r="92"
                  stroke="currentColor"
                  stroke-dasharray="3 4"
                  strokeOpacity="0.1"
                  strokeWidth="1"
                ></circle>
                <circle
                  className="text-secondary"
                  cx="100"
                  cy="100"
                  r="74"
                  stroke="currentColor"
                  strokeOpacity="0.18"
                  strokeWidth="1"
                ></circle>
                <circle
                  className="text-primary-container"
                  cx="100"
                  cy="100"
                  r="54"
                  stroke="currentColor"
                  stroke-dasharray="8 6"
                  strokeOpacity="0.25"
                  strokeWidth="1.2"
                ></circle>
                <circle
                  className="text-secondary-fixed"
                  cx="100"
                  cy="100"
                  r="32"
                  stroke="currentColor"
                  strokeOpacity="0.3"
                  strokeWidth="1"
                ></circle>

                <line
                  className="text-secondary"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  x1="100"
                  x2="100"
                  y1="4"
                  y2="16"
                ></line>
                <line
                  className="text-secondary"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  x1="100"
                  x2="100"
                  y1="184"
                  y2="196"
                ></line>
                <line
                  className="text-secondary"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  x1="4"
                  x2="16"
                  y1="100"
                  y2="100"
                ></line>
                <line
                  className="text-secondary"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  x1="184"
                  x2="196"
                  y1="100"
                  y2="100"
                ></line>

                <circle
                  className="text-tertiary-fixed"
                  cx="155"
                  cy="55"
                  fill="currentColor"
                  r="3"
                ></circle>
                <circle
                  className="text-secondary-container"
                  cx="45"
                  cy="145"
                  fill="currentColor"
                  r="2.5"
                ></circle>
                <circle
                  className="text-primary"
                  cx="140"
                  cy="150"
                  fill="currentColor"
                  r="2"
                ></circle>
                <circle
                  className="text-primary-container"
                  cx="60"
                  cy="65"
                  fill="currentColor"
                  r="3.5"
                ></circle>
              </svg>

              <svg
                className={`absolute inset-2 w-[calc(100%-1rem)] h-[calc(100%-1rem)] ${isCompleted ? "opacity-20" : "animate-[spin_4s_linear_infinite]"}`}
                fill="none"
                viewBox="0 0 180 180"
              >
                <defs>
                  <linearGradient
                    gradientUnits="userSpaceOnUse"
                    id="scanGradient"
                    x1="90"
                    x2="170"
                    y1="90"
                    y2="90"
                  >
                    <stop
                      offset="0%"
                      stopColor="#00a3ff"
                      stopOpacity="0"
                    ></stop>
                    <stop
                      offset="100%"
                      stopColor="#00d2ff"
                      stopOpacity="0.45"
                    ></stop>
                  </linearGradient>
                </defs>
                <path
                  d="M90 90 L170 90 A80 80 0 0 0 146.5 33.5 Z"
                  fill="url(#scanGradient)"
                ></path>
              </svg>

              <div className={`absolute w-24 h-24 rounded-full ${isCompleted ? "bg-tertiary/20 shadow-[0_0_30px_rgba(0,210,180,0.3)]" : "bg-primary-container/20 blur-xl animate-pulse"}`}></div>

              <div className="relative z-10 w-20 h-20 rounded-full bg-surface-container-lowest shadow-xl flex items-center justify-center">
                <div className="w-16 h-16 rounded-full bg-surface-container-high flex items-center justify-center relative shadow-inner">
                  <div
                    className="absolute w-full h-full flex items-center justify-center transition-transform duration-700 ease-out"
                    id="compass-needle"
                    style={{ transform: `rotate(${isCompleted ? 0 : 42 + (ui.progress || 0) * 3}deg)` }}
                  >
                    <svg
                      className={`w-12 h-12 ${isCompleted ? "drop-shadow-[0_0_12px_rgba(0,210,180,0.8)]" : "drop-shadow-[0_0_10px_rgba(0,210,255,0.7)]"}`}
                      fill="none"
                      viewBox="0 0 48 48"
                    >
                      <polygon
                        className={isCompleted ? "text-tertiary" : "text-secondary-container"}
                        fill="currentColor"
                        points="24,4 29,24 24,20"
                      ></polygon>
                      <polygon
                        className={isCompleted ? "text-tertiary-fixed" : "text-primary-container"}
                        fill="currentColor"
                        points="24,4 19,24 24,20"
                      ></polygon>

                      <polygon
                        className="text-outline-variant"
                        fill="currentColor"
                        points="24,44 29,24 24,28"
                      ></polygon>
                      <polygon
                        className="text-outline"
                        fill="currentColor"
                        points="24,44 19,24 24,28"
                      ></polygon>

                      <circle
                        className="text-surface-dim"
                        cx="24"
                        cy="24"
                        fill="currentColor"
                        r="3.5"
                      ></circle>
                      <circle
                        className="text-secondary"
                        cx="24"
                        cy="24"
                        fill="currentColor"
                        r="1.5"
                      ></circle>
                    </svg>
                  </div>
                </div>
              </div>

              <span className="absolute top-2 font-code-sm text-code-sm font-bold text-secondary tracking-wider">
                {"K"}
              </span>
              <span className="absolute bottom-2 font-code-sm text-code-sm font-bold text-on-surface-variant/60">
                {"G"}
              </span>
              <span className="absolute right-2 font-code-sm text-code-sm font-bold text-on-surface-variant/60">
                {"D"}
              </span>
              <span className="absolute left-2 font-code-sm text-code-sm font-bold text-on-surface-variant/60">
                {"B"}
              </span>
            </div>

            <div className="flex flex-col items-center max-w-xl mx-auto mt-space-sm gap-space-xs">
              <div className="inline-flex items-center gap-1.5 px-space-md py-0.5 rounded-full bg-primary-container/10 text-primary font-label-sm text-label-sm mb-space-xs">
                <DesignIcon name="navigation" className=" text-[16px]" />
                <span>{"Akıllı Rota Hesaplama Motoru"}</span>
              </div>
              <h1 className="font-headline-md text-headline-md text-on-surface font-bold tracking-tight">
                {isCompleted
                  ? "Rotanız hazır! En verimli paylaşım saatleri belirlendi."
                  : "Yelkenler fora! NPusula profiliniz ve paylaşımlarınız için rotayı çiziyor..."}
              </h1>
              <p className="font-body-md text-body-md text-on-surface-variant mt-space-xs leading-relaxed">
                {isCompleted
                  ? "Topluluk etkileşim frekansları ve içerik çekim noktaları başarıyla analiz edildi."
                  : "Topluluk etkileşim frekansları, zamanlama yoğunluğu ve içerik çekim noktaları taranıyor."}
              </p>
            </div>

            <div className="w-full max-w-lg mx-auto mt-space-lg flex flex-col gap-space-sm">
              <div className="flex items-center justify-between font-label-md text-label-md">
                <span className="text-on-surface font-medium flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${isCompleted ? "bg-tertiary" : "bg-secondary-container animate-ping"}`}></span>
                  <span>{isCompleted ? "Kategori sinyalleri tamamlandı" : "Kategori sinyalleri işleniyor"}</span>
                </span>
                <span
                  className="font-bold font-code-sm text-code-sm text-secondary bg-surface-container-high px-2 py-0.5 rounded-md"
                  id="progress-percent"
                >
                  {ui.progress}%
                </span>
              </div>

              <div className="w-full h-2.5 bg-surface-container-lowest rounded-full overflow-hidden p-0.5 relative shadow-inner">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-primary-container via-secondary-container to-tertiary transition-all duration-500 shadow-[0_0_12px_rgba(0,210,255,0.6)]"
                  id="progress-bar"
                  style={{ width: `${ui.progress}%` }}
                ></div>
              </div>

              <div className="flex items-center justify-between text-on-surface-variant font-code-sm text-code-sm px-1 pt-1">
                <span>{ui.mode === "mock" ? "Örnek veri" : "Canlı backend"}</span>
                <span>{ui.job?.message || "İş durumu bekleniyor"}</span>
              </div>
            </div>

            <div className="w-full max-w-lg mx-auto mt-space-lg bg-surface-container-low/90 rounded-xl p-space-md shadow-md flex flex-col gap-space-sm text-left">
              <span className="font-label-sm text-label-sm uppercase tracking-wider text-on-surface-variant font-bold px-1">
                {"Optimizasyon Aşamaları"}
              </span>

              {/* 1. Aşama */}
              <div className="flex items-center justify-between p-space-sm rounded-lg bg-surface-container-high/60 transition-colors">
                <div className="flex items-center gap-space-sm">
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center shadow-sm ${step1Done ? "bg-tertiary-container/30 text-tertiary" : "bg-surface-container-highest text-on-surface-variant"}`}>
                    <DesignIcon
                      name={step1Done ? "check" : "autorenew"}
                      className={`text-[16px] font-bold ${step1Done ? "" : "animate-spin"}`}
                    />
                  </div>
                  <span className="font-body-md text-body-md text-on-surface font-medium">
                    {"Kategori ağırlıkları indekslendi"}
                  </span>
                </div>
                <span className={`font-code-sm text-code-sm font-semibold px-2 py-0.5 rounded ${step1Done ? "text-tertiary bg-tertiary-container/10" : "text-on-surface-variant bg-surface-container-highest"}`}>
                  {step1Done ? "Tamamlandı" : "İşleniyor"}
                </span>
              </div>

              {/* 2. Aşama */}
              <div className={`flex items-center justify-between p-space-sm rounded-lg transition-colors ${step2Done ? "bg-surface-container-high/60" : "bg-secondary-container/10 shadow-[0_0_16px_rgba(0,210,255,0.08)]"}`}>
                <div className="flex items-center gap-space-sm">
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center ${step2Done ? "bg-tertiary-container/30 text-tertiary" : "bg-secondary-container/30 text-secondary-container"}`}>
                    <DesignIcon
                      name={step2Done ? "check" : "autorenew"}
                      className={`text-[16px] font-bold ${step2Done ? "" : "animate-spin"}`}
                    />
                  </div>
                  <span className="font-body-md text-body-md text-on-surface font-semibold">
                    {step2Done ? "Kitle etkileşim dalgaları analiz edildi" : "Kitle etkileşim dalgaları analiz ediliyor..."}
                  </span>
                </div>
                <div className={`flex items-center gap-1.5 font-code-sm text-code-sm font-medium ${step2Done ? "text-tertiary" : "text-secondary"}`}>
                  {!step2Done && <span className="w-1.5 h-1.5 rounded-full bg-secondary-container animate-pulse"></span>}
                  <span>{step2Done ? "Tamamlandı" : "Hesaplanıyor"}</span>
                </div>
              </div>

              {/* 3. Aşama */}
              <div className={`flex items-center justify-between p-space-sm rounded-lg transition-colors ${step3Done ? "bg-surface-container-high/60" : "bg-surface-container-lowest/40 opacity-70"}`}>
                <div className="flex items-center gap-space-sm">
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center ${step3Done ? "bg-tertiary-container/30 text-tertiary" : "bg-surface-container-highest text-on-surface-variant"}`}>
                    <DesignIcon
                      name={step3Done ? "check" : "schedule"}
                      className="text-[16px] font-bold"
                    />
                  </div>
                  <span className={`font-body-md text-body-md ${step3Done ? "text-on-surface font-semibold" : "text-on-surface-variant"}`}>
                    {step3Done ? "En verimli 3 yayın slotu belirlendi" : "En verimli 3 yayın slotu hesaplanıyor"}
                  </span>
                </div>
                <span className={`font-code-sm text-code-sm ${step3Done ? "text-tertiary font-semibold bg-tertiary-container/10 px-2 py-0.5 rounded" : "text-on-surface-variant"}`}>
                  {step3Done ? "Tamamlandı" : "Sırada"}
                </span>
              </div>
            </div>

            {/* Tamamlanma CTA Kartı */}
            {isCompleted && (
              <div className="w-full max-w-lg mx-auto mt-space-lg p-space-md rounded-xl bg-gradient-to-r from-primary-container/20 via-secondary-container/15 to-tertiary-container/20 border border-primary/40 shadow-[0_0_24px_rgba(0,163,255,0.25)] flex flex-col items-center gap-space-sm animate-[pusulaResultPop_0.3s_ease-out]">
                <div className="flex items-center gap-2 text-primary font-bold text-title-sm">
                  <DesignIcon name="check_circle" className="text-[22px] text-secondary" />
                  <span>Rotanız Başarıyla Hazırlandı!</span>
                </div>
                <p className="text-body-sm text-on-surface-variant text-center">
                  Profil sinyalleri ve kitle etkileşim dalgaları optimize edildi. Şimdi size özel en verimli paylaşım saatlerini görüntüleyebilirsiniz.
                </p>
                <button
                  onClick={() => ui.navigate("assistant")}
                  className="mt-space-xs px-space-xl py-3 rounded-xl bg-gradient-to-r from-primary-container to-secondary-container text-on-primary-container font-title-sm font-bold shadow-[0_4px_16px_rgba(0,163,255,0.4)] hover:shadow-[0_6px_24px_rgba(0,210,255,0.6)] hover:scale-[1.02] active:scale-[0.98] transition-all flex items-center justify-center gap-space-sm cursor-pointer"
                >
                  <span>Rotamı Görüntüle</span>
                  <DesignIcon name="arrow_forward" className="text-[20px]" />
                </button>
              </div>
            )}

            {/* Hata Durumu */}
            {ui.preparation.error && (
              <div className="w-full max-w-lg mx-auto mt-space-lg p-space-md rounded-xl bg-error-container/20 border border-error/40 text-error flex flex-col items-center gap-space-xs">
                <div className="flex items-center gap-2 font-semibold">
                  <DesignIcon name="error" className="text-[20px]" />
                  <span>Hazırlık işlemi tamamlanamadı</span>
                </div>
                <p className="text-body-sm text-center text-on-surface-variant">
                  {ui.preparation.error.message}
                </p>
                <button
                  onClick={ui.prepare}
                  className="mt-2 px-space-md py-1.5 rounded-lg bg-surface-container-high text-on-surface font-semibold hover:bg-surface-container-highest transition-colors cursor-pointer"
                >
                  Tekrar Dene
                </button>
              </div>
            )}

            <div className="flex items-center gap-2 mt-space-lg text-on-surface-variant font-body-sm text-body-sm">
              <DesignIcon name="info" className=" text-[18px] text-primary" />
              <span>
                {ui.mode === "mock"
                  ? "İlerleme örnek veriyle canlandırılıyor. Hazırlık tamamlandığında rotanızı görüntüleyebilirsiniz."
                  : "Profil kaydedildi ve öneri servisi çağrıldı. Rotanız hazır olduğunda görüntüleyebilirsiniz."}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-space-md w-full mt-space-md">
            <div className="bg-surface-container-low rounded-xl p-space-md flex flex-col gap-1 shadow-sm">
              <div className="flex items-center justify-between text-on-surface-variant">
                <span className="font-label-sm text-label-sm uppercase">
                  {"İçerik Çekimi"}
                </span>
                <DesignIcon
                  name="scatter_plot"
                  className=" text-[18px] text-primary"
                />
              </div>
              <span className="font-title-md text-title-md font-bold text-on-surface">
                {ui.job?.status === "completed" ? "Hazır" : "İşleniyor"}
              </span>
              <span className="font-body-sm text-body-sm text-tertiary flex items-center gap-1">
                <DesignIcon name="trending_up" className=" text-[14px]" />
                {ui.job?.message || "İş durumu bekleniyor"}
              </span>
            </div>

            <div className="bg-surface-container-low rounded-xl p-space-md flex flex-col gap-1 shadow-sm">
              <div className="flex items-center justify-between text-on-surface-variant">
                <span className="font-label-sm text-label-sm uppercase">
                  {"Kitle Penceresi"}
                </span>
                <DesignIcon
                  name="timer"
                  className=" text-[18px] text-secondary"
                />
              </div>
              <span className="font-title-md text-title-md font-bold text-on-surface">
                {"Rota hazır olduğunda"}
              </span>
              <span className="font-body-sm text-body-sm text-on-surface-variant">
                {"Zirve Etkileşim Saati"}
              </span>
            </div>

            <div className="bg-surface-container-low rounded-xl p-space-md flex flex-col gap-1 shadow-sm">
              <div className="flex items-center justify-between text-on-surface-variant">
                <span className="font-label-sm text-label-sm uppercase">
                  {"Algoritma Güveni"}
                </span>
                <DesignIcon
                  name="verified_user"
                  className=" text-[18px] text-tertiary"
                />
              </div>
              <span className="font-title-md text-title-md font-bold text-on-surface">
                {"Rota ekranında"}
              </span>
              <span className="font-body-sm text-body-sm text-secondary-container">
                {"Optimal Dağılım Skoru"}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
