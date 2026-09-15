import React from "react";
import { EXPLORE_TOPICS } from "../data/explore_topics.js";
import { useTheme } from "../theme/ThemeProvider.jsx";

export default function ExplorePage() {
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
        Explore
      </div>
      {EXPLORE_TOPICS.map((t) => (
        <div
          key={t.tag}
          style={{ padding: "16px 20px", borderBottom: `1px solid ${border}` }}
        >
          <div style={{ fontSize: 13, color: textMuted }}>Trending</div>
          <div style={{ fontWeight: 700, fontSize: 16, marginTop: 2 }}>
            #{t.tag}
          </div>
          <div style={{ fontSize: 14, color: textMuted, marginTop: 2 }}>
            {t.desc}
          </div>
          <div style={{ fontSize: 13, color: textMuted, marginTop: 4 }}>
            {t.posts}
          </div>
        </div>
      ))}
    </>
  );
}
