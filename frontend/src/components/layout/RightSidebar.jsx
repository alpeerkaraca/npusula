import React from "react";
import { Search, ChevronDown } from "lucide-react";
import { TRENDS } from "../../data/trends.js";
import { useTheme } from "../../theme/ThemeProvider.jsx";

export default function RightSidebar({ isPusula = false, goToPage }) {
  const { darkMode, panelBg, border, textPrimary, textMuted } = useTheme();
  return (
    <aside className="right-sidebar">
      {isPusula ? (
        <>
          <section className="discovery-card">
            <h3>
              Popüler Gündem <span>↗</span>
            </h3>
            {[
              ["Türkiye Trendi", "TEKNOFEST", "84.2B"],
              ["Teknoloji & AI", "YapayZeka", "45.8B"],
              ["Tarih & Toplum", "12eylül", "29.1B"],
            ].map(([category, tag, count]) => (
              <button
                className="trend-link"
                key={tag}
                onClick={() => goToPage?.("explore")}
              >
                <small>{category}</small>
                <strong>#{tag}</strong>
                <small>{count} Gönderi</small>
              </button>
            ))}
          </section>
          <section className="discovery-card">
            <h3>Algoritmik Takip</h3>
            <p>
              NPusula karar destek katmanı için örnek sinyaller ve içerik
              önerileri.
            </p>
          </section>
        </>
      ) : (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                gap: 8,
                background: panelBg,
                border: `1px solid ${border}`,
                borderRadius: 999,
                padding: "9px 14px",
              }}
            >
              <Search size={16} color={textMuted} />
              <input
                placeholder="Arama yap"
                aria-label="Arama yap"
                style={{
                  border: "none",
                  outline: "none",
                  background: "none",
                  color: textPrimary,
                  fontSize: 14,
                  width: "100%",
                }}
              />
            </div>
            <div
              style={{
                width: 34,
                height: 34,
                borderRadius: "50%",
                background: darkMode ? "#242a35" : "#e4e6ea",
                flexShrink: 0,
              }}
            />
            <ChevronDown size={16} color={textMuted} />
          </div>

          <div
            style={{
              background: panelBg,
              border: `1px solid ${border}`,
              borderRadius: 16,
              padding: 16,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 12,
              }}
            >
              <span style={{ fontWeight: 700, fontSize: 16 }}>Popüler</span>
              <button
                style={{
                  background: "none",
                  border: "none",
                  color: "#00a3ff",
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                Tümünü gör
              </button>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {TRENDS.map((t) => (
                <div key={t.tag}>
                  <div style={{ fontWeight: 700, fontSize: 14 }}>#{t.tag}</div>
                  <div style={{ color: textMuted, fontSize: 13 }}>
                    {t.posts}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </aside>
  );
}
