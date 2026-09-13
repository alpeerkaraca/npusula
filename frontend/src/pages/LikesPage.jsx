import React from "react";
import { Heart } from "lucide-react";
import { LIKED_POSTS } from "../data/liked_posts.js";
import { useTheme } from "../theme/ThemeProvider.jsx";

export default function LikesPage() {
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
        Likes
      </div>
      {LIKED_POSTS.map((p) => (
        <div
          key={p.id}
          style={{
            display: "flex",
            gap: 12,
            padding: "16px 20px",
            borderBottom: `1px solid ${border}`,
          }}
        >
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: "50%",
              background: "linear-gradient(135deg, #00a3ff, #00d2ff)",
              flexShrink: 0,
            }}
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14 }}>
              <span style={{ fontWeight: 700 }}>{p.name}</span>{" "}
              <span style={{ color: textMuted }}>
                {p.handle} · {p.time}
              </span>
            </div>
            <div style={{ fontSize: 14, marginTop: 4 }}>{p.text}</div>
          </div>
          <Heart size={16} color="#00a3ff" style={{ flexShrink: 0 }} />
        </div>
      ))}
    </>
  );
}
