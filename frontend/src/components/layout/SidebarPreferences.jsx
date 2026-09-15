import React from "react";
import { Settings, Play, Moon } from "lucide-react";
import ToggleSwitch from "../ui/ToggleSwitch.jsx";
import { useTheme } from "../../theme/ThemeProvider.jsx";

/**
 * Bottom section of Sidebar: media toggle (social only), dark mode toggle,
 * and settings button.
 *
 * `isPusula` hides the media toggle because it's irrelevant in the Pusula
 * shell — the value is preserved so it takes effect when returning to social.
 */
export default function SidebarPreferences({
  mediaOnly,
  setMediaOnly,
  activePage,
  goToPage,
  isPusula,
}) {
  const { darkMode, setDarkMode, textMuted } = useTheme();
  return (
    <div
      className="sidebar-preferences"
      style={{ display: "flex", flexDirection: "column", gap: 14 }}
    >
      {/* Medya toggle — only meaningful in social mode */}
      {!isPusula && (
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
            <Play size={20} aria-hidden="true" />
            Medya
          </span>
          <ToggleSwitch checked={mediaOnly} onChange={setMediaOnly} />
        </div>
      )}

      {/* Dark mode toggle — always visible */}
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
          <Moon size={20} aria-hidden="true" />
          Karanlık mod
        </span>
        <ToggleSwitch checked={darkMode} onChange={setDarkMode} />
      </div>

      {/* Settings link */}
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
        <Settings size={18} aria-hidden="true" />
        Ayarlar
      </button>
    </div>
  );
}
