import React from "react";
import { Settings, PlusCircle, Moon, Play } from "lucide-react";
import { NAV_ITEMS } from "../../data/nav_items.js";
import { EXTRA_NAV_ITEMS } from "../../data/extra_nav_items.js";
import { NOTIFICATIONS } from "../../data/notifications.js";
import ToggleSwitch from "../ui/ToggleSwitch.jsx";
import Logo from "../ui/Logo.jsx";
import { useTheme } from "../../theme/ThemeProvider.jsx";

export default function Sidebar({
  activePage,
  goToPage,
  mediaOnly,
  setMediaOnly,
}) {
  const { darkMode, setDarkMode, border, textPrimary, textMuted } = useTheme();
  return (
    <aside className="sidebar">
      <Logo />

      <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {NAV_ITEMS.map(({ id, icon: Icon, label, showBadge }) => {
          const isActive = id === activePage;
          return (
            <button
              aria-label={label}
              aria-current={isActive ? "page" : undefined}
              key={id}
              onClick={() => goToPage(id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "10px 12px",
                borderRadius: 10,
                border: "none",
                background: isActive
                  ? darkMode
                    ? "rgba(79,140,255,0.12)"
                    : "rgba(79,140,255,0.08)"
                  : "transparent",
                color: isActive ? "#00a3ff" : textPrimary,
                fontWeight: isActive ? 600 : 500,
                fontSize: 15,
                cursor: "pointer",
                textAlign: "left",
                width: "100%",
              }}
            >
              <Icon size={20} strokeWidth={2} />
              <span style={{ flex: 1 }}>{label}</span>
              {showBadge && NOTIFICATIONS.length > 0 && (
                <span
                  style={{
                    background: "#ef4444",
                    color: "#ffffff",
                    fontSize: 11,
                    fontWeight: 800,
                    borderRadius: 999,
                    minWidth: 20,
                    height: 20,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "0 6px",
                  }}
                >
                  {NOTIFICATIONS.length}
                </span>
              )}
            </button>
          );
        })}

        <div style={{ borderTop: `1px solid ${border}`, margin: "8px 0" }} />

        {EXTRA_NAV_ITEMS.map(({ id, icon: Icon, label, tag }) => {
          const isActive = id === activePage;
          return (
            <button
              aria-label={label}
              aria-current={isActive ? "page" : undefined}
              key={id}
              onClick={() => goToPage(id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "10px 12px",
                borderRadius: 10,
                border: "none",
                background: isActive
                  ? darkMode
                    ? "rgba(79,140,255,0.12)"
                    : "rgba(79,140,255,0.08)"
                  : "transparent",
                color: isActive ? "#00a3ff" : textPrimary,
                fontWeight: isActive ? 600 : 500,
                fontSize: 15,
                cursor: "pointer",
                textAlign: "left",
                width: "100%",
              }}
            >
              <Icon size={20} strokeWidth={2} />
              <span style={{ flex: 1 }}>{label}</span>
              {tag && (
                <span
                  style={{
                    background: "#173248",
                    color: "#8ec9f5",
                    fontSize: 10,
                    fontWeight: 800,
                    letterSpacing: 0.5,
                    borderRadius: 6,
                    padding: "2px 6px",
                  }}
                >
                  {tag}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <button
        className="new-post-button"
        onClick={() => goToPage("home")}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
          padding: "12px",
          borderRadius: 999,
          border: "none",
          background: "linear-gradient(135deg, #0091ff 0%, #00d2ff 100%)",
          color: "#06131f",
          fontWeight: 700,
          fontSize: 15,
          cursor: "pointer",
        }}
      >
        <PlusCircle size={18} />
        Yeni Gönder
      </button>

      <div
        className="sidebar-preferences"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span
            className="preference-label"
            style={{ fontSize: 14, color: textMuted }}
          >
            <Play size={20} />
            Medya
          </span>
          <ToggleSwitch checked={mediaOnly} onChange={setMediaOnly} />
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span
            className="preference-label"
            style={{ fontSize: 14, color: textMuted }}
          >
            <Moon size={20} />
            Karanlık mod
          </span>
          <ToggleSwitch checked={darkMode} onChange={setDarkMode} />
        </div>
        <button
          onClick={() => goToPage("settings")}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            background: "none",
            border: "none",
            color: activePage === "settings" ? "#00a3ff" : textMuted,
            fontSize: 14,
            cursor: "pointer",
            padding: "6px 0",
          }}
        >
          <Settings size={18} />
          Ayarlar
        </button>
      </div>
    </aside>
  );
}
