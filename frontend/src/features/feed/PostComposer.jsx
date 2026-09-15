import React from "react";
import {
  Image as ImageIcon,
  BarChart2,
  Info,
  Smile,
  Calendar,
  Gift,
} from "lucide-react";
import { useTheme } from "../../theme/ThemeProvider.jsx";

export default function PostComposer({ draft, setDraft }) {
  const { darkMode, border, textPrimary, textMuted } = useTheme();
  return (
    <div
      className="post-composer"
      style={{ padding: "18px 20px", borderBottom: `1px solid ${border}` }}
    >
      <div style={{ display: "flex", gap: 12 }}>
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: "50%",
            background: darkMode ? "#242a35" : "#e4e6ea",
            flexShrink: 0,
          }}
        />
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Gönderi oluşturmak için..."
          rows={2}
          style={{
            flex: 1,
            background: "none",
            border: "none",
            outline: "none",
            resize: "none",
            color: textPrimary,
            fontSize: 16,
            fontFamily: "inherit",
            marginTop: 8,
          }}
        />
      </div>
      <div
        className="composer-toolbar"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 8,
        }}
      >
        <div style={{ display: "flex", gap: 14, color: "#00a3ff" }}>
          <ImageIcon size={18} style={{ cursor: "pointer" }} />
          <BarChart2 size={18} style={{ cursor: "pointer" }} />
          <Info size={18} style={{ cursor: "pointer" }} />
          <Smile size={18} style={{ cursor: "pointer" }} />
          <Calendar size={18} style={{ cursor: "pointer" }} />
          <Gift size={18} style={{ cursor: "pointer" }} />
        </div>
        <button
          disabled={!draft.trim()}
          style={{
            padding: "8px 18px",
            borderRadius: 999,
            border: "none",
            background: draft.trim()
              ? "linear-gradient(135deg, #0091ff 0%, #00d2ff 100%)"
              : darkMode
                ? "#1c2029"
                : "#e4e6ea",
            color: draft.trim() ? "#06131f" : textMuted,
            fontWeight: 700,
            fontSize: 14,
            cursor: draft.trim() ? "pointer" : "default",
          }}
        >
          Gönder
        </button>
      </div>
    </div>
  );
}
