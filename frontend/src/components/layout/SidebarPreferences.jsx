import React from "react";
import { Settings } from "lucide-react";
import { useTheme } from "../../theme/ThemeProvider.jsx";

/**
 * Bottom section of Sidebar: just the Settings link.
 * Dark mode and media toggles are available in the Settings page.
 */
export default function SidebarPreferences({ activePage, goToPage }) {
  const { textMuted } = useTheme();
  return (
    <div className="sidebar-preferences">
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
