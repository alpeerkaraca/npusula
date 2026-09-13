import React from "react";
import PostComposer from "../features/feed/PostComposer.jsx";
import PostCard from "../features/feed/PostCard.jsx";
import { POSTS } from "../data/posts.js";
import { useTheme } from "../theme/ThemeProvider.jsx";

export default function HomePage({
  tab,
  setTab,
  draft,
  setDraft,
  expanded,
  setExpanded,
  postState,
  toggleLike,
  toggleRepost,
  toggleCommentBox,
  setCommentDraft,
  submitComment,
}) {
  const { border, textPrimary, textMuted } = useTheme();
  return (
    <>
      <div style={{ display: "flex", borderBottom: `1px solid ${border}` }}>
        {[
          { id: "feed", label: "Akış" },
          { id: "media", label: "Medya" },
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              flex: 1,
              padding: "16px 0",
              background: "none",
              border: "none",
              borderBottom:
                tab === t.id ? "2px solid #00a3ff" : "2px solid transparent",
              color: tab === t.id ? textPrimary : textMuted,
              fontWeight: tab === t.id ? 700 : 500,
              fontSize: 15,
              cursor: "pointer",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Composer */}
      <PostComposer draft={draft} setDraft={setDraft} />

      {/* Posts */}
      {POSTS.map((post, i) => (
        <PostCard
          key={i}
          expanded={expanded}
          setExpanded={setExpanded}
          postState={postState}
          toggleLike={toggleLike}
          toggleRepost={toggleRepost}
          toggleCommentBox={toggleCommentBox}
          setCommentDraft={setCommentDraft}
          submitComment={submitComment}
          post={post}
          i={i}
        />
      ))}
    </>
  );
}
