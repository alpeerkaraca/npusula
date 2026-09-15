import React, { useEffect, useRef } from "react";
import { PlusCircle } from "lucide-react";
import { NAV_ITEMS } from "../../data/nav_items.js";
import { EXTRA_NAV_ITEMS } from "../../data/extra_nav_items.js";
import { NOTIFICATIONS } from "../../data/notifications.js";
import Logo from "../ui/Logo.jsx";
import NavItem from "./NavItem.jsx";
import SidebarPreferences from "./SidebarPreferences.jsx";
import { useTheme } from "../../theme/ThemeProvider.jsx";

/**
 * Primary left sidebar. Shared between social and Pusula shells.
 *
 * `isPusula` is derived from activePage in App and forwarded here so the
 * preferences section can hide the media toggle when it's irrelevant.
 */
export default function Sidebar({
  activePage,
  goToPage,
  mediaOnly,
  setMediaOnly,
  isPusula,
}) {
  const { border } = useTheme();
  const sidebarRef = useRef(null);

  // Reset scroll position on every page transition so the user always sees
  // the top of the nav regardless of how far they had scrolled before.
  useEffect(() => {
    sidebarRef.current?.scrollTo({ top: 0, behavior: "instant" });
  }, [activePage]);

  return (
    <aside className="sidebar" ref={sidebarRef}>
      <Logo />

      <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {NAV_ITEMS.map(({ id, icon, label, showBadge }) => (
          <NavItem
            key={id}
            id={id}
            icon={icon}
            label={label}
            isActive={id === activePage}
            onClick={() => goToPage(id)}
            badge={showBadge ? NOTIFICATIONS.length : 0}
          />
        ))}

        <div style={{ borderTop: `1px solid ${border}`, margin: "8px 0" }} />

        {EXTRA_NAV_ITEMS.map(({ id, icon, label, tag }) => (
          <NavItem
            key={id}
            id={id}
            icon={icon}
            label={label}
            isActive={id === activePage}
            onClick={() => goToPage(id)}
            tag={tag}
          />
        ))}
      </nav>

      <button
        className="new-post-button"
        onClick={() => goToPage("home")}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
          padding: "12px",
          borderRadius: 999,
          border: "none",
          background: "linear-gradient(135deg, #0091ff 0%, #00d2ff 100%)",
          color: "#06131f",
          fontWeight: 700,
          fontSize: 15,
          cursor: "pointer",
        }}
      >
        <PlusCircle size={18} aria-hidden="true" />
        Yeni Gönder
      </button>

      <SidebarPreferences
        activePage={activePage}
        goToPage={goToPage}
      />
    </aside>
  );
}
