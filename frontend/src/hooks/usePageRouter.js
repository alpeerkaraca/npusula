import { useState, useEffect, useCallback } from "react";

/**
 * All valid page IDs that can appear as URL pathnames.
 * Must stay in sync with App.jsx's page rendering logic.
 */
const VALID_PAGES = new Set([
  "home",
  "notifications",
  "messages",
  "explore",
  "play",
  "communities",
  "saved",
  "likes",
  "teknofest",
  "settings",
  // Pusula pages
  "assistant",
  "ideas",
  "setup",
  "preparing",
]);

/**
 * Reads the current page ID from the URL pathname.
 * Falls back to "home" for unknown paths or the root "/".
 */
function readPageFromUrl() {
  const segment = window.location.pathname.replace(/^\//, "").split("/")[0];
  return segment && VALID_PAGES.has(segment) ? segment : "home";
}

/**
 * Drop-in replacement for the `activePage` + `goToPage` pair in App.jsx.
 *
 * - Syncs `activePage` with `window.location.pathname` on every navigation.
 * - Responds to the browser's back / forward buttons via `popstate`.
 * - Works without a router library; just uses the History API.
 *
 * The dev server must have `historyApiFallback: true` so that navigating
 * directly to e.g. `/assistant` doesn't return a 404.
 */
export function usePageRouter() {
  const [activePage, setActivePage] = useState(readPageFromUrl);

  useEffect(() => {
    function onPopState() {
      setActivePage(readPageFromUrl());
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const goToPage = useCallback((id) => {
    const target = VALID_PAGES.has(id) ? id : "home";
    setActivePage(target);
    const url = target === "home" ? "/" : `/${target}`;
    if (window.location.pathname !== url) {
      window.history.pushState({ page: target }, "", url);
    }
  }, []);

  return { activePage, goToPage };
}
