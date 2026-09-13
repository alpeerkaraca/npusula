import React from "react";
import { Search, PenSquare, ArrowLeft } from "lucide-react";
import { CONVERSATIONS } from "../data/conversations.js";
import { useTheme } from "../theme/ThemeProvider.jsx";

export default function MessagesPage({
  openConversation,
  setOpenConversation,
}) {
  const { darkMode, border, textPrimary, textMuted } = useTheme();
  return (
    <>
      {!openConversation && (
        <>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "20px",
              borderBottom: `1px solid ${border}`,
            }}
          >
            <span style={{ fontWeight: 800, fontSize: 20 }}>Messages</span>
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
              <button
                style={{
                  background: "none",
                  border: "none",
                  color: "#00a3ff",
                  fontWeight: 600,
                  fontSize: 14,
                  textDecoration: "underline",
                  cursor: "pointer",
                }}
              >
                Message requests
              </button>
              <Search
                size={18}
                color={textMuted}
                style={{ cursor: "pointer" }}
              />
              <PenSquare
                size={18}
                color={textMuted}
                style={{ cursor: "pointer" }}
              />
            </div>
          </div>
          {CONVERSATIONS.map((c) => (
            <button
              key={c.id}
              onClick={() => setOpenConversation(c)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 14,
                width: "100%",
                padding: "16px 20px",
                background: "none",
                border: "none",
                borderBottom: `1px solid ${border}`,
                cursor: "pointer",
                textAlign: "left",
              }}
            >
              <div
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: "50%",
                  background: darkMode ? "#242a35" : "#e4e6ea",
                  flexShrink: 0,
                }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{ fontWeight: 700, fontSize: 15, color: textPrimary }}
                >
                  {c.name}
                </div>
                <div
                  style={{
                    fontSize: 14,
                    color: textMuted,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {c.preview}
                </div>
              </div>
              <span style={{ fontSize: 13, color: textMuted, flexShrink: 0 }}>
                {c.time}
              </span>
            </button>
          ))}
        </>
      )}

      {openConversation && (
        <div
          style={{ display: "flex", flexDirection: "column", height: "100%" }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "16px 20px",
              borderBottom: `1px solid ${border}`,
            }}
          >
            <button
              onClick={() => setOpenConversation(null)}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                color: textPrimary,
              }}
            >
              <ArrowLeft size={20} />
            </button>
            <div
              style={{
                width: 34,
                height: 34,
                borderRadius: "50%",
                background: darkMode ? "#242a35" : "#e4e6ea",
              }}
            />
            <span style={{ fontWeight: 700, fontSize: 15 }}>
              {openConversation.name}
            </span>
          </div>
          <div
            style={{
              flex: 1,
              padding: 20,
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            {openConversation.thread.map((m, i) => (
              <div
                key={i}
                style={{
                  alignSelf: m.from === "me" ? "flex-end" : "flex-start",
                  background:
                    m.from === "me"
                      ? "linear-gradient(135deg, #0091ff 0%, #00d2ff 100%)"
                      : darkMode
                        ? "#1c2129"
                        : "#eceef1",
                  color: m.from === "me" ? "#06131f" : textPrimary,
                  padding: "10px 14px",
                  borderRadius: 16,
                  fontSize: 14,
                  maxWidth: 320,
                }}
              >
                {m.text}
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
