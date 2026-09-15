import React from "react";
import { NOTIFICATIONS } from "../data/notifications.js";
import { useTheme } from "../theme/ThemeProvider.jsx";

export default function NotificationsPage() {
  const { darkMode, border, textPrimary, textMuted } = useTheme();
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
        Notifications
      </div>
      {NOTIFICATIONS.map((n) => (
        <div
          key={n.id}
          style={{
            display: "flex",
            gap: 14,
            padding: "16px 20px",
            borderBottom: `1px solid ${border}`,
          }}
        >
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: "50%",
              background: darkMode
                ? "rgba(79,140,255,0.12)"
                : "rgba(79,140,255,0.08)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <n.icon size={16} color="#00a3ff" />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, color: textPrimary }}>
              <span style={{ fontWeight: 700 }}>{n.name}</span> {n.action}
            </div>
            {n.detail && (
              <div style={{ fontSize: 13, color: textMuted, marginTop: 2 }}>
                {n.detail}
              </div>
            )}
          </div>
          <span style={{ fontSize: 13, color: textMuted, flexShrink: 0 }}>
            {n.time}
          </span>
        </div>
      ))}
    </>
  );
}
