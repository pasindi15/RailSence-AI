import { createContext, useContext, useEffect, useState } from "react";

const STORAGE_KEY = "railsense_theme_preference";
const ThemeContext = createContext(null);

function getSystemTheme() {
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function resolveTheme(preference) {
  return preference === "system" ? getSystemTheme() : preference;
}

export function ThemeProvider({ children }) {
  const [preference, setPreference] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || "system";
    } catch {
      return "system";
    }
  });
  const [theme, setTheme] = useState(() => resolveTheme(preference));

  // Apply the resolved theme to the document as soon as it changes, and
  // persist the user's explicit preference (not the resolved value, so
  // "system" keeps following OS changes until the user picks a side).
  useEffect(() => {
    const resolved = resolveTheme(preference);
    setTheme(resolved);
    document.documentElement.setAttribute("data-theme", resolved);
    try {
      localStorage.setItem(STORAGE_KEY, preference);
    } catch {
      // localStorage unavailable (private mode, etc.) - theme still works for this session
    }
  }, [preference]);

  // While following "system", react live to OS-level theme changes.
  useEffect(() => {
    if (preference !== "system" || !window.matchMedia) return;
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      const resolved = getSystemTheme();
      setTheme(resolved);
      document.documentElement.setAttribute("data-theme", resolved);
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [preference]);

  const toggleTheme = () => setPreference(theme === "dark" ? "light" : "dark");

  return (
    <ThemeContext.Provider value={{ theme, preference, setPreference, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside a ThemeProvider");
  return ctx;
}
