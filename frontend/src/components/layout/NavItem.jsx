import React from "react";
import { useTheme } from "../../theme/ThemeProvider.jsx";

/** Badge (notification count) */
function NavBadge({ count }) {
  return (
    <span
      className="nav-badge"
      aria-label={`${count} bildirim`}
    >
      {count}
    </span>
  );
}

/** AI / BETA tag */
function NavTag({ text }) {
  return (
    <span className="nav-tag">
      {text}
    </span>
  );
}

/**
 * Single navigation button used inside Sidebar.
 * Keeps all visual state (active, dark/light) out of the parent list.
 */
export default function NavItem({ id, icon: Icon, label, isActive, onClick, badge, tag }) {
  const { darkMode, textPrimary } = useTheme();
  return (
    <button
      aria-label={label}
      aria-current={isActive ? "page" : undefined}
      onClick={onClick}
      className="nav-item"
      data-active={isActive ? "true" : "false"}
      style={{
        color: isActive ? "#00a3ff" : textPrimary,
        fontWeight: isActive ? 600 : 500,
        background: isActive
          ? darkMode
            ? "rgba(79,140,255,0.12)"
            : "rgba(79,140,255,0.08)"
          : "transparent",
      }}
    >
      <Icon size={20} strokeWidth={2} aria-hidden="true" />
      <span className="nav-item__label">{label}</span>
      {badge > 0 && <NavBadge count={badge} />}
      {tag && <NavTag text={tag} />}
    </button>
  );
}
