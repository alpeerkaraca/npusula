import React from "react";

export default function Logo() {
  return (
    <div className="brand-logo" aria-label="nSosyal Beta">
      <div className="social-brand">
        <svg width="56" height="58" viewBox="0 0 56 58" aria-hidden="true">
          <defs>
            <linearGradient id="nsosyal-brand">
              <stop stopColor="#12cbd5" />
              <stop offset="1" stopColor="#343aff" />
            </linearGradient>
          </defs>
          <path
            fill="url(#nsosyal-brand)"
            d="M0 0h16l22 34V0h18v58H38L17 25v33H0z"
          />
        </svg>
        <span>BETA</span>
      </div>
      <div className="dashboard-brand">
        <DashboardBrand />
      </div>
    </div>
  );
}
function DashboardBrand() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: 12,
            background: "linear-gradient(135deg, #0091ff 0%, #00d2ff 100%)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 800,
            fontSize: 20,
            color: "#0b1118",
            flexShrink: 0,
            position: "relative",
          }}
        >
          N
          <span
            style={{
              position: "absolute",
              bottom: -2,
              right: -2,
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: "#00d2ff",
              border: "2px solid #0b1118",
            }}
          />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontWeight: 800, fontSize: 17, color: "#f1f5f9" }}>
            nSosyal
          </span>
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: 0.5,
              color: "#8ec9f5",
              background: "#173248",
              borderRadius: 6,
              padding: "2px 6px",
            }}
          >
            BETA
          </span>
        </div>
      </div>
      <span style={{ fontSize: 12.5, color: "#94a3b8" }}>Karar Destek Ağı</span>
    </div>
  );
}
