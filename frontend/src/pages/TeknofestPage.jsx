import React from "react";
import { useTheme } from "../theme/ThemeProvider.jsx";

export default function TeknofestPage() {
  const { border, textMuted } = useTheme();
  return (
    <div style={{ padding: "20px" }}>
      <div style={{ fontWeight: 800, fontSize: 20, marginBottom: 4 }}>
        TEKNOFEST Kayıt
      </div>
      <div style={{ fontSize: 14, color: textMuted, marginBottom: 20 }}>
        Takımını kaydet, yarışma programını takip et.
      </div>
      <div
        style={{
          border: `1px solid ${border}`,
          borderRadius: 14,
          padding: 18,
          marginBottom: 16,
        }}
      >
        <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 6 }}>
          Kayıt durumu
        </div>
        <div style={{ fontSize: 14, color: textMuted }}>
          Henüz kayıt oluşturmadın.
        </div>
      </div>
      <div
        style={{
          border: `1px solid ${border}`,
          borderRadius: 14,
          padding: 18,
          marginBottom: 20,
        }}
      >
        <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 6 }}>
          Yaklaşan yarışmalar
        </div>
        <div style={{ fontSize: 14, color: textMuted, lineHeight: 1.8 }}>
          Roket Yarışması — 7. Gün
          <br />
          İnsansız Kara Aracı — Final
          <br />
          Uluslararası İHA Yarışması — 6. Gün
        </div>
      </div>
      <button
        style={{
          padding: "10px 20px",
          borderRadius: 999,
          border: "none",
          background: "linear-gradient(135deg, #0091ff 0%, #00d2ff 100%)",
          color: "#06131f",
          fontWeight: 700,
          fontSize: 14,
          cursor: "pointer",
        }}
      >
        Takım Kaydı Oluştur
      </button>
    </div>
  );
}
