import React from "react";

export default function ProfileAvatar({ size = 40 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label="HWTH101 profil resmi"
      style={{ flexShrink: 0, display: "block" }}
    >
      <circle cx="32" cy="32" r="31" fill="#202b43" stroke="#32a6ef" strokeWidth="2" />
      <path d="M13 44h38" stroke="#04c7d4" strokeWidth="2" strokeLinecap="round" />
      <text x="32" y="36" textAnchor="middle" fill="#f3f7ff" fontFamily="Arial, sans-serif" fontSize="11" fontWeight="700" textLength="52" lengthAdjust="spacingAndGlyphs">HWTH101</text>
    </svg>
  );
}
