import React from "react";
import DesignIcon from "../DesignIcon.jsx";
import { evidenceLabel, scoreInterval, signedScore } from "../format.js";
export default function SlotCard({ slot, index, onPlan, busy }) {
  const ci = scoreInterval(slot.liftCiLow, slot.liftCiHigh);
  return (
    <article className="relative min-w-0 rounded-2xl bg-surface-container p-space-lg shadow-xl flex flex-col justify-between gap-space-lg">
      <div
        className={`absolute inset-x-0 top-0 h-1 rounded-t-2xl ${index === 0 ? "bg-gradient-to-r from-primary via-secondary-container to-primary-container" : "bg-surface-container-highest"}`}
      />
      <div
        className={`absolute -top-3 right-6 px-space-sm py-0.5 rounded-full text-label-sm font-bold ${index === 0 ? "bg-primary-container text-on-primary-container" : "bg-surface-container-highest text-on-surface"}`}
      >
        {["🥇", "🥈", "🥉"][index]} {index + 1}. ÖNERİ{" "}
        {index === 0 ? "• MUTLAK ZİRVE" : ""}
      </div>
      <div className="flex flex-col gap-space-md pt-space-xs">
        <div className="min-w-0">
          <span className="text-label-sm text-primary uppercase tracking-wider">
            {slot.confidenceLabel} Güven
          </span>
          {/* The backend window label is a range ("15.00–18.00"), so the row
              wraps instead of clipping in the narrow three-column grid. */}
          <div className="flex flex-wrap items-baseline gap-x-2 min-w-0">
            <span className="text-headline-lg font-bold">{slot.day}</span>
            <span className="text-headline-lg font-bold text-primary break-words">
              {slot.time}
            </span>
          </div>
        </div>
        <div className="p-space-sm rounded-xl bg-surface-container-lowest flex flex-col gap-2">
          <div className="flex justify-between gap-2 text-body-sm">
            <span>Gözlemsel Zaman Etkisi</span>
            <strong className="text-tertiary">
              {signedScore(slot.observationalTimeLift)}
            </strong>
          </div>
          <div className="w-full bg-surface-container-high h-2 rounded-full overflow-hidden">
            <div
              className="bg-gradient-to-r from-primary to-tertiary h-full rounded-full"
              style={{ width: `${slot.rankPercent}%` }}
            />
          </div>
          <div className="text-code-sm text-on-surface-variant">
            Pencereler arası konum: %{Math.round(slot.rankPercent)}
          </div>
          <div className="flex justify-between gap-2 text-code-sm">
            <span>Destek</span>
            <strong>
              {slot.supportPostCount.toLocaleString("tr-TR")} gönderi
            </strong>
          </div>
          <div className="flex justify-between gap-2 text-code-sm">
            <span>Göreli Potansiyel</span>
            <strong>{signedScore(slot.relativePotential)}</strong>
          </div>
          <div className="text-code-sm text-on-surface-variant">
            {ci ? `${ci} · ` : ""}
            {slot.supportUserCount.toLocaleString("tr-TR")} kullanıcı
          </div>
        </div>
        <div>
          <span className="text-label-sm text-on-surface-variant uppercase">
            Kanıt Seviyesi
          </span>
          <div className="flex items-center gap-space-xs px-space-sm py-1.5 rounded-lg bg-surface-container-high">
            <DesignIcon name="verified" className="text-secondary text-[18px]" />
            {evidenceLabel(slot.evidenceLevel)}
          </div>
        </div>
      </div>
      <button
        disabled={busy}
        onClick={() => onPlan(slot)}
        className={`w-full py-space-sm px-space-md rounded-xl font-semibold flex items-center justify-center gap-space-xs ${index === 0 ? "bg-gradient-to-r from-primary-container to-secondary-container text-on-primary-container" : "bg-surface-container-high text-on-surface"}`}
      >
        <DesignIcon name="event_upcoming" />
        Bu Saate Planla
      </button>
    </article>
  );
}
