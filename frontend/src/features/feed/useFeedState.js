import { useState } from "react";
import { POSTS } from "../../data/posts.js";
export function useFeedState() {
  const [tab, setTab] = useState("feed");
  const [draft, setDraft] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("npusula-draft")) || "";
    } catch {
      return "";
    }
  });
  const [expanded, setExpanded] = useState({});
  const [postState, setPostState] = useState(() =>
    POSTS.map((p) => ({
      liked: false,
      reposted: false,
      boosts: p.boosts,
      reposts: p.reposts,
      comments: p.comments,
      commentBoxOpen: false,
      commentDraft: "",
      extraComments: [],
    })),
  );

  function toggleLike(i) {
    setPostState((prev) =>
      prev.map((s, idx) =>
        idx === i
          ? {
              ...s,
              liked: !s.liked,
              boosts: s.liked ? s.boosts - 1 : s.boosts + 1,
            }
          : s,
      ),
    );
  }

  function toggleRepost(i) {
    setPostState((prev) =>
      prev.map((s, idx) =>
        idx === i
          ? {
              ...s,
              reposted: !s.reposted,
              reposts: s.reposted ? s.reposts - 1 : s.reposts + 1,
            }
          : s,
      ),
    );
  }

  function toggleCommentBox(i) {
    setPostState((prev) =>
      prev.map((s, idx) =>
        idx === i ? { ...s, commentBoxOpen: !s.commentBoxOpen } : s,
      ),
    );
  }

  function setCommentDraft(i, value) {
    setPostState((prev) =>
      prev.map((s, idx) => (idx === i ? { ...s, commentDraft: value } : s)),
    );
  }

  function submitComment(i) {
    setPostState((prev) =>
      prev.map((s, idx) => {
        if (idx !== i || !s.commentDraft.trim()) return s;
        return {
          ...s,
          comments: s.comments + 1,
          extraComments: [...s.extraComments, s.commentDraft.trim()],
          commentDraft: "",
        };
      }),
    );
  }
  return {
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
  };
}
