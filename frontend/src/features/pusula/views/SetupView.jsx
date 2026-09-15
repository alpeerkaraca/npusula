import React from "react";
import { usePusula } from "../PusulaProvider.jsx";
import DesignIcon from "../DesignIcon.jsx";
export default function SetupView() {
  const ui = usePusula();
  return (
    <div className="pusula-view">
      <div className="flex flex-col w-full max-w-5xl mx-auto pb-space-2xl">
        <div className="relative w-full">
          <div className="absolute -top-12 left-1/2 -translate-x-1/2 w-3/4 h-64 bg-gradient-to-b from-primary-container/15 via-secondary-container/5 to-transparent blur-3xl pointer-events-none rounded-full"></div>

          <div className="relative flex flex-col items-center text-center pt-space-xs pb-space-md">
            <div className="inline-flex items-center gap-space-xs px-space-md py-1.5 rounded-full bg-surface-container-high/90 shadow-md backdrop-blur-md mb-space-md">
              <div className="w-2 h-2 rounded-full bg-secondary-container animate-pulse shadow-[0_0_8px_rgba(0,210,255,0.8)]"></div>
              <DesignIcon
                name="explore"
                className=" text-[16px] text-primary"
              />
              <span className="font-code-sm text-code-sm uppercase tracking-widest text-primary font-semibold">
                {"NPusula Kurulum"}
              </span>
              <span className="text-outline-variant text-[12px] font-mono">
                {"•"}
              </span>
              <span className="font-label-sm text-label-sm text-on-surface-variant font-medium">
                {"Adım 1 / 2"}
              </span>
            </div>

            <h1 className="font-headline-lg text-headline-lg text-on-surface font-bold tracking-tight">
              {"\n        Hesabınızı Anlatın\n      "}
            </h1>
            <p className="mt-space-xs max-w-xl font-body-md text-body-md text-on-surface-variant">
              {
                "\n        İçerik türlerinizi seçin, NPusula paylaşımlarınızı ve kitlenizi analiz etsin, size özel rotayı çıkarsın.\n      "
              }
            </p>
          </div>

          <div className="relative mt-space-sm rounded-2xl bg-surface-container-low shadow-xl p-space-lg sm:p-space-xl backdrop-blur-sm overflow-hidden">
            <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-transparent via-primary-container to-transparent opacity-75"></div>

            <div className="flex flex-wrap items-center justify-between gap-space-sm mb-space-lg">
              <div className="flex items-center gap-space-sm">
                <div className="w-8 h-8 rounded-lg bg-surface-container-high flex items-center justify-center text-primary">
                  <DesignIcon name="tune" className=" text-[20px]" />
                </div>
                <div className="flex flex-col">
                  <span className="font-title-sm text-title-sm text-on-surface">
                    {"Odak Alanları"}
                  </span>
                  <span className="font-body-sm text-body-sm text-on-surface-variant">
                    {"Profilinizin algoritmik eşleşmesini belirler"}
                  </span>
                </div>
              </div>
              <div
                className="flex items-center gap-space-xs px-space-sm py-1 rounded-full bg-surface-container-highest text-on-surface"
                id="selection-counter"
              >
                <DesignIcon
                  name="check_circle"
                  className=" text-[16px] text-secondary-container"
                />
                <span className="font-label-sm text-label-sm font-semibold">
                  <span id="count-num">{ui.interests.length}</span>
                  {" / 5 Seçildi"}
                </span>
              </div>
            </div>

            <div
              className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-space-md"
              id="categories-grid"
            >
              {[
                { id: "teknoloji", label: "Teknoloji", sub: "Donanım, Ar-Ge & Sistemler", icon: "memory" },
                { id: "araba", label: "Araba / Otomotiv", sub: "Mobilite & Elektrikli Araçlar", icon: "directions_car" },
                { id: "yazilim", label: "Yazılım", sub: "Geliştirme, Mimari & Bulut", icon: "terminal" },
                { id: "oyun", label: "Oyun / E-Spor", sub: "Turnuvalar & Oyun Geliştirme", icon: "sports_esports" },
                { id: "yasam", label: "Yaşam / Vlog", sub: "Gündelik, Seyahat & Deneyim", icon: "videocam" },
                { id: "yapayzekâ", label: "Yapay Zekâ", sub: "LLM, Otomasyon & Veri Bilimi", icon: "smart_toy" },
                { id: "tasarim", label: "Tasarım & Sanat", sub: "UI/UX, 3D & Dijital İllüstrasyon", icon: "palette" },
                { id: "bilim", label: "Bilim & Havacılık", sub: "Uzay, Fizik & Savunma Sanayii", icon: "rocket" },
                { id: "girisimcilik", label: "Girişimcilik & Finans", sub: "Yatırım, FinTech & Büyüme", icon: "insights" },
              ].map((cat) => {
                const isSelected = ui.interests.includes(cat.id);
                return (
                  <button
                    key={cat.id}
                    data-cat={cat.id}
                    type="button"
                    onClick={() => ui.toggleInterest(cat.id)}
                    aria-pressed={isSelected}
                    className={`category-card group relative p-space-md rounded-xl cursor-pointer transition-all duration-200 shadow-sm flex flex-col justify-between h-36 border ${
                      isSelected
                        ? "is-selected bg-[#202d39] border-[#00a3ff] shadow-[0_0_16px_rgba(0,163,255,0.25)]"
                        : "bg-surface-container hover:bg-surface-container-high/80 border-transparent"
                    }`}
                  >
                    <div className="flex items-start justify-between w-full">
                      <div
                        className={`w-10 h-10 rounded-xl flex items-center justify-center transition-all ${
                          isSelected
                            ? "bg-primary-container/20 text-primary shadow-[0_0_12px_rgba(0,163,255,0.25)] group-hover:scale-105"
                            : "bg-surface-container-high text-on-surface-variant group-hover:text-primary"
                        }`}
                      >
                        <DesignIcon name={cat.icon} className="text-[22px]" />
                      </div>
                      <div
                        className={`custom-checkbox w-6 h-6 rounded-lg flex items-center justify-center transition-all ${
                          isSelected
                            ? "bg-primary-container text-on-primary-container shadow-[0_0_10px_rgba(0,163,255,0.4)]"
                            : "bg-surface-container-highest text-transparent border border-outline-variant/30"
                        }`}
                      >
                        <DesignIcon
                          name="check"
                          className={`text-[16px] font-bold ${isSelected ? "opacity-100" : "opacity-0"}`}
                        />
                      </div>
                    </div>
                    <div className="flex flex-col text-left">
                      <span
                        className={`font-title-sm text-title-sm font-semibold transition-colors ${
                          isSelected ? "text-primary font-bold" : "text-on-surface"
                        }`}
                      >
                        {cat.label}
                      </span>
                      <span className="font-body-sm text-body-sm text-on-surface-variant">
                        {cat.sub}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>

            <div className="mt-space-lg p-space-md rounded-xl bg-surface-container-lowest/80 flex items-start sm:items-center gap-space-md shadow-sm">
              <div className="w-8 h-8 rounded-full bg-secondary-container/20 text-secondary-container flex items-center justify-center shrink-0">
                <DesignIcon name="lightbulb" className=" text-[18px]" />
              </div>
              <div className="flex-1">
                <p className="font-body-sm text-body-sm text-on-surface-variant leading-relaxed">
                  <span className="font-label-sm text-label-sm font-bold text-secondary">
                    {"İpucu:"}
                  </span>
                  {
                    " En az 2, en fazla 5 kategori seçmeniz önerilir. Bu tercihler zamanla paylaşımlarınıza ve etkileşim modelinize göre dinamik olarak güncellenir.\n          "
                  }
                </p>
              </div>
            </div>

            <div className="mt-space-xl pt-space-md flex flex-col-reverse sm:flex-row items-center justify-between gap-space-md">
              <button
                className="px-space-md py-space-sm text-on-surface-variant hover:text-on-surface font-title-sm text-title-sm transition-colors flex items-center gap-space-xs rounded-xl hover:bg-surface-container-high"
                type="button"
                onClick={() => ui.navigate("assistant")}
                aria-label="Şimdilik Atla"
              >
                <span>{"Şimdilik Atla"}</span>
              </button>
              <div className="flex items-center gap-space-md w-full sm:w-auto">
                <button
                  className="w-full sm:w-auto px-space-xl py-space-sm rounded-full bg-gradient-to-r from-primary-container to-secondary-container text-on-primary-container font-title-sm text-title-sm font-bold shadow-[0_4px_20px_rgba(0,163,255,0.4)] hover:shadow-[0_6px_28px_rgba(0,210,255,0.5)] hover:scale-[1.02] active:scale-[0.98] transition-all flex items-center justify-center gap-space-sm"
                  id="submit-btn"
                  type="button"
                  onClick={ui.prepare}
                  disabled={
                    ui.interests.length < 2 ||
                    ui.preparation.status === "loading"
                  }
                  aria-label="Pusulamı Oluştur arrow_forward"
                >
                  <span>{"Pusulamı Oluştur"}</span>
                  <DesignIcon
                    name="arrow_forward"
                    className=" text-[20px] transition-transform group-hover:translate-x-1"
                  />
                </button>
              </div>
            </div>
          </div>

          <div className="mt-space-lg grid grid-cols-1 md:grid-cols-3 gap-space-md">
            <div className="p-space-md rounded-xl bg-surface-container-low shadow-sm flex items-center gap-space-md">
              <div className="w-10 h-10 rounded-xl bg-tertiary-container/20 text-tertiary flex items-center justify-center">
                <DesignIcon name="radar" className=" text-[20px]" />
              </div>
              <div className="flex flex-col">
                <span className="font-title-sm text-title-sm text-on-surface font-semibold">
                  {"Anlık Ağ Keşfi"}
                </span>
                <span className="font-body-sm text-body-sm text-on-surface-variant">
                  {"Topluluk trendlerine göre indeksleme"}
                </span>
              </div>
            </div>
            <div className="p-space-md rounded-xl bg-surface-container-low shadow-sm flex items-center gap-space-md">
              <div className="w-10 h-10 rounded-xl bg-primary-container/20 text-primary flex items-center justify-center">
                <DesignIcon name="psychology" className=" text-[20px]" />
              </div>
              <div className="flex flex-col">
                <span className="font-title-sm text-title-sm text-on-surface font-semibold">
                  {"Karar Destek Modeli"}
                </span>
                <span className="font-body-sm text-body-sm text-on-surface-variant">
                  {"Etkileşim optimizasyonu & rota planı"}
                </span>
              </div>
            </div>
            <div className="p-space-md rounded-xl bg-surface-container-low shadow-sm flex items-center gap-space-md">
              <div className="w-10 h-10 rounded-xl bg-secondary-container/20 text-secondary flex items-center justify-center">
                <DesignIcon name="format_image_left" className=" text-[20px]" />
              </div>
              <div className="flex flex-col">
                <span className="font-title-sm text-title-sm text-on-surface font-semibold">
                  {"Kişiselleştirilmiş Veri"}
                </span>
                <span className="font-body-sm text-body-sm text-on-surface-variant">
                  {"Tamamen şeffaf ve kontrol edilebilir"}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
