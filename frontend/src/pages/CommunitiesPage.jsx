import React from "react";
import { COMMUNITIES } from "../data/communities.js";
import { useTheme } from "../theme/ThemeProvider.jsx";

export default function CommunitiesPage() {
  const { border, textPrimary, textMuted } = useTheme();
  return (
    <>
      <div
        style={{
          padding: "20px",
          borderBottom: `1px solid ${border}`,
          fontWeight: 800,
          fontSize: 20,
        }}
      >
        Communities
      </div>
      {COMMUNITIES.map((c) => (
        <div
          key={c.id}
          style={{ padding: "16px 20px", borderBottom: `1px solid ${border}` }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: 12,
                background: "linear-gradient(135deg, #00a3ff, #00d2ff)",
                flexShrink: 0,
              }}
            />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>{c.name}</div>
              <div style={{ fontSize: 13, color: textMuted }}>{c.members}</div>
            </div>
            <button
              style={{
                padding: "7px 16px",
                borderRadius: 999,
                border: `1px solid ${border}`,
                background: "none",
                color: textPrimary,
                fontWeight: 600,
                fontSize: 13,
                cursor: "pointer",
                flexShrink: 0,
              }}
            >
              Joined
            </button>
          </div>
          <div style={{ fontSize: 14, color: textMuted, marginTop: 8 }}>
            {c.desc}
          </div>
          <div style={{ fontSize: 13, color: "#00a3ff", marginTop: 6 }}>
            {c.tag}
          </div>
        </div>
      ))}
    </>
  );
}
