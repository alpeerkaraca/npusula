import React, { createContext, useContext, useState } from "react";
const ThemeContext = createContext(null);
export function ThemeProvider({ children }) {
  const [darkMode, setDarkMode] = useState(true);
  const bg = darkMode ? "#0e141b" : "#f5f6f8";
  const panelBg = darkMode ? "#161c23" : "#ffffff";
  const border = darkMode ? "#252e3b" : "#e4e6ea";
  const textPrimary = darkMode ? "#dde3ed" : "#12151b";
  const textMuted = darkMode ? "#9ba7b5" : "#6b7280";
  return (
    <ThemeContext.Provider
      value={{
        darkMode,
        setDarkMode,
        bg,
        panelBg,
        border,
        textPrimary,
        textMuted,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}
export function useTheme() {
  const theme = useContext(ThemeContext);
  if (!theme) throw new Error("useTheme requires ThemeProvider");
  return theme;
}
