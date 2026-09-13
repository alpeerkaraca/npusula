import React from "react";
import { MessageCircle, ChevronDown, ChevronUp } from "lucide-react";
import { useTheme } from "../../theme/ThemeProvider.jsx";

export default function MessagesBar({ messagesOpen, setMessagesOpen }) {
  const { panelBg, border, textPrimary } = useTheme();
  return (
    <div
      className="messages-bar"
      style={{
        position: "fixed",
        bottom: 0,
        background: panelBg,
        border: `1px solid ${border}`,
        borderBottom: "none",
        borderRadius: "12px 12px 0 0",
        overflow: "hidden",
      }}
    >
      <button
        onClick={() => setMessagesOpen(!messagesOpen)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 16px",
          background: "none",
          border: "none",
          color: textPrimary,
          fontWeight: 700,
          fontSize: 14,
          cursor: "pointer",
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <MessageCircle size={16} /> Mesajlar
        </span>
        {messagesOpen ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
      </button>
    </div>
  );
}
