import React, { useEffect, useRef } from "react";

export default function CompassTransition({ onComplete, direction = "enter", light = false }) {
  const complete = useRef(onComplete);
  complete.current = onComplete;
  useEffect(() => {
    if (typeof window === "undefined") {
      complete.current?.();
      return;
    }
    const reduced =
      typeof window !== "undefined" && window.matchMedia
        ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
        : false;
    const timer = setTimeout(() => complete.current?.(), reduced ? 120 : 2200);
    return () => clearTimeout(timer);
  }, []);
  return (
    <div className={`compass-transition compass-${direction} ${light ? "compass-light" : ""}`} role="status" aria-live="polite">
      <div className="compass-transition-art" aria-hidden="true">
        <svg viewBox="0 0 320 320" className="compass-dial">
          <defs>
            <linearGradient id="compass-accent" x2="1" y2="1">
              <stop stopColor="#04c7d4" /><stop offset="1" stopColor="#3449ff" />
            </linearGradient>
          </defs>
          <circle cx="160" cy="160" r="146" fill="#191c23" stroke="#383e4c" />
          <circle cx="160" cy="160" r="135" fill="none" stroke="url(#compass-accent)" strokeWidth="2" />
          {Array.from({ length: 48 }, (_, i) => (
            <path key={i} d={`M160 36v${i % 6 === 0 ? 13 : 5}`} transform={`rotate(${i * 7.5} 160 160)`} stroke={i % 6 === 0 ? "#a9b6c8" : "#434c5d"} strokeWidth="2" />
          ))}
          <g fill="#a9b6c8" fontSize="15" textAnchor="middle" fontFamily="inherit">
            <text x="160" y="76">K</text><text x="251" y="165">D</text>
            <text x="160" y="256">G</text><text x="69" y="165">B</text>
          </g>
          <g className="compass-needle">
            <path d="M160 70 183 160 160 150 137 160Z" fill="url(#compass-accent)" />
            <path d="M160 250 137 160 160 170 183 160Z" fill="#667387" />
          </g>
          <circle cx="160" cy="160" r="9" fill="#dce8f8" stroke="#1c1f26" strokeWidth="4" />
        </svg>
      </div>
      <span className="compass-transition-label">{direction === "return" ? "Ana Sayfa’ya dönülüyor…" : "NPusula’ya geçiliyor…"}</span>
    </div>
  );
}
