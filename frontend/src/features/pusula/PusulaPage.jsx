import React from "react";
import { usePusula } from "./PusulaProvider.jsx";
import ScheduleView from "./views/ScheduleView.jsx";
import IdeasView from "./views/IdeasView.jsx";
import SetupView from "./views/SetupView.jsx";
import PreparingView from "./views/PreparingView.jsx";
export const PUSULA_PAGES = [
  ["assistant", "Paylaşım Saatleri", ScheduleView],
  ["ideas", "Fikir Danışmanı", IdeasView],
  ["setup", "Kurulum", SetupView],
  ["preparing", "Hazırlık", PreparingView],
];
export default function PusulaPage({ page }) {
  const ui = usePusula();
  const View = PUSULA_PAGES.find(([id]) => id === page)?.[2] || ScheduleView;
  return (
    <section className={`pusula-page page-${page}`}>
      <div className="pusula-page-meta">
        <span className="demo-caption">
          {ui.mode === "mock" ? "Demo veriler" : "Backend bağlantısı"}
        </span>
        {page !== "setup" && (
          <button onClick={() => ui.navigate("setup")}>Hesap Kurulumu</button>
        )}
      </div>
      <View />
      {ui.mutation.status === "loading" && (
        <div className="request-state" role="status">
          Kaydediliyor…
        </div>
      )}
      {ui.mutation.error && (
        <div className="request-state request-error" role="alert">
          {ui.mutation.error.message} İşlemi tekrar deneyebilirsiniz.
        </div>
      )}
      {page === "assistant" && ui.plans.length > 0 && (
        <section className="local-plans">
          <h3>Kaydedilen Planlar</h3>
          {ui.plans.map((plan) => (
            <p key={plan.id}>
              {new Date(plan.startsAt).toLocaleString("tr-TR", {
                timeZone: "Europe/Istanbul",
              })}{" "}
              · {ui.mode === "mock" ? "Demo kayıt" : "Sunucu kaydı"}
            </p>
          ))}
        </section>
      )}
    </section>
  );
}
