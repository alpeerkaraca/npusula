import React from "react";
import { Settings } from "lucide-react";
import ToggleSwitch from "../components/ui/ToggleSwitch.jsx";
import { useTheme } from "../theme/ThemeProvider.jsx";

export default function SettingsPage({ mediaOnly, setMediaOnly }) {
  const { darkMode, setDarkMode, border } = useTheme();
  return (
    <div style={{ padding: 20 }}>
      <div style={{ fontWeight: 800, fontSize: 20, marginBottom: 20 }}>
        Settings
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 0",
          borderBottom: `1px solid ${border}`,
        }}
      >
        <span style={{ fontSize: 15 }}>Media only mode</span>
        <ToggleSwitch checked={mediaOnly} onChange={setMediaOnly} />
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 0",
          borderBottom: `1px solid ${border}`,
        }}
      >
        <span style={{ fontSize: 15 }}>Dark mode</span>
        <ToggleSwitch checked={darkMode} onChange={setDarkMode} />
      </div>
    </div>
  );
}
