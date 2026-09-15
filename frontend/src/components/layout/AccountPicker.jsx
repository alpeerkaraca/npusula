import React, { useState } from "react";
import { ChevronDown, UserPlus, UserRound } from "lucide-react";

/**
 * Turkish display names for the backend's HISTORY_DEPTH_NAMES vocabulary.
 * `depthLabel` falls back to the raw code so an unknown value shows something
 * diagnosable rather than an empty label.
 */
const DEPTH_LABELS = {
  cold_start: "Geçmiş yok",
  very_low_history: "Çok az geçmiş",
  low_history: "Az geçmiş",
  medium_history: "Orta geçmiş",
  high_history: "Zengin geçmiş",
};
export function depthLabel(depth) {
  return DEPTH_LABELS[depth] || depth || "";
}

/** "31253@N15 · Zengin geçmiş · 1376 gönderi" (count omitted when unknown). */
export function accountLabel(user) {
  if (!user) return "";
  const parts = [user.userId, depthLabel(user.historyDepth)];
  if (typeof user.postCount === "number") parts.push(`${user.postCount} gönderi`);
  return parts.filter(Boolean).join(" · ");
}

/**
 * Switches the account every request is made for.
 *
 * Opens on click and closes on selection or Escape. There is deliberately no
 * document-level outside-click listener: the UI check harness mounts App under
 * plain Node with no jsdom, so touching `document` in an effect would throw on
 * all 14 pages. It also avoids `aria-pressed`, because the harness reads the
 * first `aria-pressed` element positionally.
 */
export default function AccountPicker({
  userId = "",
  users = [],
  onSelect,
  onNewUser,
}) {
  const [open, setOpen] = useState(false);
  const current = users.find((user) => user.userId === userId);
  const summary = current
    ? `${current.userId} · ${depthLabel(current.historyDepth)}`
    : "Yeni hesap";

  return (
    <div
      className="account-picker"
      onKeyDown={(event) => {
        if (event.key === "Escape") setOpen(false);
      }}
    >
      <button
        type="button"
        className="operator"
        aria-haspopup="menu"
        aria-expanded={open}
        title={`Aktif hesap: ${userId || "yok"}`}
        onClick={() => setOpen((value) => !value)}
      >
        <span>
          <UserRound size={18} />
        </span>
        {summary}
        <ChevronDown size={15} />
      </button>
      {open && (
        <div className="account-picker-menu" role="menu">
          <p className="account-picker-heading">Hesap seç</p>
          {users.map((user) => (
            <button
              key={user.userId}
              type="button"
              role="menuitem"
              className="account-picker-item"
              data-active={user.userId === userId ? "true" : undefined}
              onClick={() => {
                setOpen(false);
                onSelect?.(user.userId);
              }}
            >
              <strong>{user.userId}</strong>
              <span>
                {depthLabel(user.historyDepth)} · {user.postCount} gönderi
              </span>
            </button>
          ))}
          <button
            type="button"
            role="menuitem"
            className="account-picker-item"
            onClick={() => {
              setOpen(false);
              onNewUser?.();
            }}
          >
            <strong>
              <UserPlus size={14} /> Yeni hesap
            </strong>
            <span>Geçmiş yok · soğuk başlangıç yolu</span>
          </button>
          {!users.length && (
            <p className="account-picker-empty">
              Hesap listesi yüklenemedi; yalnız yeni hesap açılabilir.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
