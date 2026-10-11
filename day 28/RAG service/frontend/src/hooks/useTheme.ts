/** Управление темой (светлая/тёмная), сохранение в localStorage. */

import { useEffect, useState } from "react";

const KEY = "raglab-theme";

export function initTheme(): void {
  const stored = localStorage.getItem(KEY);
  const darkPref = stored === "dark"
    || (stored === null && window.matchMedia?.("(prefers-color-scheme: dark)")?.matches === true);
  applyTheme(darkPref);
}

export function applyTheme(dark: boolean): void {
  document.documentElement.classList.toggle("dark", dark);
  localStorage.setItem(KEY, dark ? "dark" : "light");
}

export function useTheme(): { dark: boolean; toggle: () => void } {
  const [dark, setDark] = useState(document.documentElement.classList.contains("dark"));
  const toggle = () => {
    const next = !dark;
    applyTheme(next);
    setDark(next);
  };
  return { dark, toggle };
}