import React from "react";
import { GAMES } from "../data/games.js";
import { useTheme } from "../theme/ThemeProvider.jsx";

export default function GamesPage() {
  const { border, textMuted } = useTheme();
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
        Play
      </div>
      {GAMES.map((g) => (
        <div
          key={g.id}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            padding: "16px 20px",
            borderBottom: `1px solid ${border}`,
          }}
        >
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
            <div style={{ fontWeight: 700, fontSize: 15 }}>{g.name}</div>
            <div style={{ fontSize: 13, color: textMuted, marginTop: 2 }}>
              {g.desc}
            </div>
            <div style={{ fontSize: 12, color: textMuted, marginTop: 2 }}>
              {g.players}
            </div>
          </div>
          <button
            style={{
              padding: "8px 16px",
              borderRadius: 999,
              border: "none",
              background: "linear-gradient(135deg, #0091ff 0%, #00d2ff 100%)",
              color: "#06131f",
              fontWeight: 700,
              fontSize: 13,
              cursor: "pointer",
              flexShrink: 0,
            }}
          >
            Play
          </button>
        </div>
      ))}
    </>
  );
}
