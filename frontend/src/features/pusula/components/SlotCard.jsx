import React from "react";
import DesignIcon from "../DesignIcon.jsx";
export default function SlotCard({ slot, index, onPlan, busy }) {
  return (
    <article className="relative rounded-2xl bg-surface-container p-space-lg shadow-xl flex flex-col justify-between gap-space-lg">
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
        <div>
          <span className="text-label-sm text-primary uppercase tracking-wider">
            {slot.label}
          </span>
          <div className="flex items-baseline gap-2">
            <span className="text-headline-lg font-bold">{slot.day}</span>
            <span className="text-headline-lg font-bold text-primary">
              {slot.time}
            </span>
          </div>
        </div>
        <div className="p-space-sm rounded-xl bg-surface-container-lowest flex flex-col gap-2">
          <div className="flex justify-between gap-2 text-body-sm">
            <span>Kitle Çevrimiçi Oranı</span>
            <strong className="text-tertiary">
              %{slot.onlinePercent} Çevrimiçi
            </strong>
          </div>
          <div className="w-full bg-surface-container-high h-2 rounded-full overflow-hidden">
            <div
              className="bg-gradient-to-r from-primary to-tertiary h-full rounded-full"
              style={{ width: `${slot.onlinePercent}%` }}
            />
          </div>
          <div className="flex justify-between gap-2 text-code-sm">
            <span>Erişim İndeksi</span>
            <strong>
              {slot.reach.toLocaleString("tr-TR")}+ Tekil Kullanıcı
            </strong>
          </div>
        </div>
        <div>
          <span className="text-label-sm text-on-surface-variant uppercase">
            Tavsiye Edilen Format
          </span>
          <div className="flex items-center gap-space-xs px-space-sm py-1.5 rounded-lg bg-surface-container-high">
            <DesignIcon
              name="play_circle"
              className="text-secondary text-[18px]"
            />
            {slot.format}
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
