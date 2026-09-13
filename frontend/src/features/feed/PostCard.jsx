import React from "react";
import {
  Bookmark,
  Rocket,
  MessageSquare,
  Repeat2,
  BarChart3,
  Share2,
} from "lucide-react";
import { useTheme } from "../../theme/ThemeProvider.jsx";

export default function PostCard({
  expanded,
  setExpanded,
  postState,
  toggleLike,
  toggleRepost,
  toggleCommentBox,
  setCommentDraft,
  submitComment,
  post,
  i,
}) {
  const { darkMode, border, textPrimary, textMuted } = useTheme();
  return (
    <article
      className="post-card"
      style={{ padding: "18px 20px", borderBottom: `1px solid ${border}` }}
    >
      <div style={{ display: "flex", gap: 12 }}>
        <div
          className={
            post.name === "TEKNOFEST" ? "teknofest-avatar" : "post-avatar"
          }
          style={{
            width: 44,
            height: 44,
            borderRadius: "50%",
            background: "linear-gradient(135deg, #00a3ff, #00d2ff)",
            flexShrink: 0,
          }}
        >
          {post.name === "TEKNOFEST" && <span>TEKNOFEST</span>}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              gap: 6,
            }}
          >
            <span style={{ fontWeight: 700, fontSize: 15 }}>{post.name}</span>
            {post.verified && (
              <span
                style={{
                  width: 16,
                  height: 16,
                  borderRadius: "50%",
                  background: "#00a3ff",
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 10,
                  color: "#06131f",
                  fontWeight: 900,
                }}
              >
                ✓
              </span>
            )}
            <span style={{ color: textMuted, fontSize: 14 }}>
              {post.handle} · {post.time}
            </span>
          </div>

          {post.tags.length > 0 && (
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 8,
                marginTop: 2,
              }}
            >
              {post.tags.map((tag) => (
                <span key={tag} style={{ color: "#00a3ff", fontSize: 14 }}>
                  {tag}
                </span>
              ))}
            </div>
          )}

          <p style={{ fontSize: 15, lineHeight: 1.5, margin: "8px 0 0" }}>
            {expanded[i] || !post.hasMore
              ? post.text
              : post.text.slice(0, 60) + "… "}
            {post.hasMore && !expanded[i] && (
              <button
                onClick={() => setExpanded({ ...expanded, [i]: true })}
                style={{
                  background: "none",
                  border: "none",
                  color: textMuted,
                  fontStyle: "italic",
                  fontSize: 15,
                  cursor: "pointer",
                  padding: 0,
                }}
              >
                Daha fazla göster
              </button>
            )}
          </p>

          {post.media?.poster ? (
            <div
              className="teknofest-poster"
              role="img"
              aria-label="TEKNOFEST Güneydoğu, 30 Eylül–4 Ekim 2026, Şanlıurfa GAP Havalimanı"
            />
          ) : post.media?.images ? (
            <div className="feed-media-grid">
              {post.media.images.map((image) => (
                <img
                  key={image.src}
                  src={image.src}
                  alt={image.alt}
                  loading="lazy"
                  onError={(event) => {
                    event.currentTarget.onerror = null;
                    event.currentTarget.src = "/assets/image-fallback.svg";
                  }}
                />
              ))}
            </div>
          ) : (
            post.media && (
              <div
                style={{
                  marginTop: 12,
                  borderRadius: 14,
                  overflow: "hidden",
                  border: `1px solid ${border}`,
                }}
              >
                <div
                  style={{
                    aspectRatio: "16/9",
                    background: darkMode
                      ? "linear-gradient(160deg, #1a2230, #0e131c)"
                      : "linear-gradient(160deg, #dfe3ea, #c9ced8)",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 10,
                    padding: 16,
                    textAlign: "center",
                  }}
                >
                  <div
                    style={{
                      width: 52,
                      height: 52,
                      borderRadius: "50%",
                      background: "rgba(255,255,255,0.15)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <div
                      style={{
                        width: 0,
                        height: 0,
                        borderTop: "10px solid transparent",
                        borderBottom: "10px solid transparent",
                        borderLeft: "16px solid #fff",
                        marginLeft: 4,
                      }}
                    />
                  </div>
                  <span style={{ fontWeight: 700, fontSize: 13 }}>
                    {post.media.title}
                  </span>
                  <span style={{ fontSize: 12, color: textMuted }}>
                    {post.media.sub}
                  </span>
                </div>
              </div>
            )
          )}

          <div
            className="post-actions"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginTop: 14,
              maxWidth: 420,
              color: textMuted,
              fontSize: 13,
            }}
          >
            <button
              onClick={() => toggleCommentBox(i)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                background: "none",
                border: "none",
                padding: 0,
                cursor: "pointer",
                color: postState[i].commentBoxOpen ? "#00a3ff" : textMuted,
              }}
            >
              <MessageSquare size={16} /> {postState[i].comments}
            </button>
            <button
              onClick={() => toggleRepost(i)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                background: "none",
                border: "none",
                padding: 0,
                cursor: "pointer",
                color: postState[i].reposted ? "#10b981" : textMuted,
              }}
            >
              <Repeat2 size={16} /> {postState[i].reposts}
            </button>
            <button
              onClick={() => toggleLike(i)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                background: "none",
                border: "none",
                padding: 0,
                cursor: "pointer",
                color: postState[i].liked ? "#00a3ff" : textMuted,
              }}
            >
              <Rocket
                size={16}
                fill={postState[i].liked ? "#00a3ff" : "none"}
              />{" "}
              {postState[i].boosts}
            </button>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <BarChart3 size={16} /> {post.views}
            </span>
            <Bookmark size={16} style={{ cursor: "pointer" }} />
            <Share2 size={16} style={{ cursor: "pointer" }} />
          </div>

          {postState[i].extraComments.length > 0 && (
            <div
              style={{
                marginTop: 12,
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              {postState[i].extraComments.map((c, ci) => (
                <div key={ci} style={{ display: "flex", gap: 10 }}>
                  <div
                    style={{
                      width: 26,
                      height: 26,
                      borderRadius: "50%",
                      background: darkMode ? "#242a35" : "#e4e6ea",
                      flexShrink: 0,
                    }}
                  />
                  <span
                    style={{
                      fontSize: 13,
                      color: textPrimary,
                      background: darkMode ? "#161b24" : "#f1f2f5",
                      borderRadius: 12,
                      padding: "6px 12px",
                    }}
                  >
                    {c}
                  </span>
                </div>
              ))}
            </div>
          )}

          {postState[i].commentBoxOpen && (
            <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
              <div
                style={{
                  width: 26,
                  height: 26,
                  borderRadius: "50%",
                  background: darkMode ? "#242a35" : "#e4e6ea",
                  flexShrink: 0,
                }}
              />
              <input
                value={postState[i].commentDraft}
                onChange={(e) => setCommentDraft(i, e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") submitComment(i);
                }}
                placeholder="Post your reply"
                style={{
                  flex: 1,
                  background: "none",
                  border: `1px solid ${border}`,
                  borderRadius: 999,
                  padding: "7px 14px",
                  color: textPrimary,
                  fontSize: 13,
                  outline: "none",
                }}
              />
              <button
                onClick={() => submitComment(i)}
                disabled={!postState[i].commentDraft.trim()}
                style={{
                  padding: "7px 14px",
                  borderRadius: 999,
                  border: "none",
                  background: postState[i].commentDraft.trim()
                    ? "linear-gradient(135deg, #0091ff 0%, #00d2ff 100%)"
                    : darkMode
                      ? "#1c2029"
                      : "#e4e6ea",
                  color: postState[i].commentDraft.trim()
                    ? "#06131f"
                    : textMuted,
                  fontWeight: 700,
                  fontSize: 13,
                  cursor: postState[i].commentDraft.trim()
                    ? "pointer"
                    : "default",
                  flexShrink: 0,
                }}
              >
                Reply
              </button>
            </div>
          )}
        </div>
      </div>
    </article>
  );
}
