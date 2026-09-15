import React from "react";
import { useTheme } from "../../theme/ThemeProvider.jsx";

export default function ToggleSwitch({ checked, onChange }) {
  const { darkMode } = useTheme();
  return (
    <button
      onClick={() => onChange(!checked)}
      aria-pressed={checked}
      style={{
        width: 36,
        height: 20,
        borderRadius: 999,
        background: checked
          ? "linear-gradient(135deg, #0091ff 0%, #00d2ff 100%)"
          : darkMode ? "#2a2f3a" : "#a1afbf",
        position: "relative",
        border: "none",
        cursor: "pointer",
        transition: "background 0.2s ease",
        flexShrink: 0,
      }}
    >
      <span
        style={{
          position: "absolute",
          top: 2,
          left: checked ? 18 : 2,
          width: 16,
          height: 16,
          borderRadius: "50%",
          background: "#fff",
          transition: "left 0.2s ease",
        }}
      />
    </button>
  );
}
