import React from "react";
import { usePusula } from "../PusulaProvider.jsx";
import DesignIcon from "../DesignIcon.jsx";
import RequestState from "../RequestState.jsx";
import SlotCard from "../components/SlotCard.jsx";
export default function ScheduleView() {
  const ui = usePusula();
  const data = ui.recommendations.data;
  return (
    <div className="pusula-view flex flex-col gap-space-xl">
      <section className="relative rounded-2xl bg-surface-container-low p-space-xl shadow-xl overflow-hidden">
        <div className="absolute -right-16 -top-16 w-80 h-80 bg-primary-container/10 blur-3xl rounded-full pointer-events-none" />
        <div className="relative flex flex-col md:flex-row justify-between gap-space-lg">
          <div className="max-w-2xl">
            <span className="text-code-sm text-primary uppercase tracking-widest">
              <DesignIcon name="explore" /> Yapay Zeka Karar Destek Çekirdeği
            </span>
            <h1 className="text-headline-lg font-bold mt-space-xs">
              N-Pusula Karar Destek Rotanız
            </h1>
            <p className="text-body-md text-on-surface-variant mt-space-xs">
              Profilinize ve kitle etkileşim paternlerinize göre optimize
              edilmiş haftalık etkileşim haritası.
            </p>
          </div>
          <div className="bg-surface-container-high rounded-xl px-space-md py-space-sm self-start shrink-0">
            <span className="text-code-sm uppercase text-on-surface-variant">
              Sinyal Güveni
            </span>
            <div className="text-tertiary text-title-md font-bold">
              {data ? data.confidenceLabel : "Sinyal bekleniyor"}
            </div>
            {data ? (
              <span className="text-code-sm text-on-surface-variant block">
                {data.activeTopic}
                {data.coldStart
                  ? " · paylaşım geçmişi yok, öneriler kategori düzeyinde"
                  : ""}
              </span>
            ) : null}
          </div>
        </div>
      </section>
      <section className="flex flex-col gap-space-lg">
        <header className="flex justify-between gap-2">
          <h2 className="text-headline-sm font-bold">
            <DesignIcon name="schedule" className="text-primary" /> En İyi
            Paylaşım Saatleri (Top 3 Slot)
          </h2>
          <small className="text-on-surface-variant">
            {data ? new Date(data.updatedAt).toLocaleString("tr-TR") : ""}
          </small>
        </header>
        <RequestState
          task={ui.recommendations}
          retry={ui.reloadRecommendations}
        >
          {data?.slots?.length ? (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-space-md">
              {data.slots.map((slot, index) => (
                <SlotCard
                  key={slot.id}
                  slot={slot}
                  index={index}
                  busy={ui.mutation.status === "loading"}
                  onPlan={ui.plan}
                />
              ))}
            </div>
          ) : (
            <div className="request-state">
              Henüz paylaşım saati önerisi yok. Hesap kurulumunu tamamlayın.
            </div>
          )}
        </RequestState>
      </section>
      <section className="p-space-xl rounded-2xl bg-surface-container-low relative overflow-hidden">
        <div className="relative flex flex-col lg:flex-row items-center gap-space-lg justify-between">
          <div>
            <h2 className="text-headline-md font-bold">
              Aklında yeni bir içerik fikri mi var?
            </h2>
            <p className="text-body-md text-on-surface-variant mt-space-xs">
              Fikrini paylaş, NPusula en doğru formatı ve paylaşım zamanını
              değerlendirsin.
            </p>
          </div>
          <button
            onClick={() => ui.navigate("ideas")}
            className="pusula-primary whitespace-nowrap"
          >
            <DesignIcon name="lightbulb" /> İçerik Fikri Danış{" "}
            <DesignIcon name="arrow_forward" />
          </button>
        </div>
      </section>
    </div>
  );
}
