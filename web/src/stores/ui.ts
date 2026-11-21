import { create } from "zustand";

import i18n, { type AppLocale } from "@/lib/i18n";
import { readStored, storageKeys, writeStored } from "@/lib/storage";

export type Theme = "light" | "dark";

function initialTheme(): Theme {
  const stored = readStored(storageKeys.theme);
  if (stored === "light" || stored === "dark") return stored;
  const prefersLight =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-color-scheme: light)").matches;
  return prefersLight ? "light" : "dark";
}

function initialLocale(): AppLocale {
  const stored = readStored(storageKeys.locale);
  return stored === "en" ? "en" : "zh";
}

interface UiState {
  theme: Theme;
  locale: AppLocale;
  sidebarCollapsed: boolean;
  mobileNavOpen: boolean;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setLocale: (locale: AppLocale) => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
  setMobileNavOpen: (open: boolean) => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  theme: initialTheme(),
  locale: initialLocale(),
  sidebarCollapsed: readStored(storageKeys.sidebarCollapsed) === "1",
  mobileNavOpen: false,

  setTheme: (theme) => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    writeStored(storageKeys.theme, theme);
    set({ theme });
  },

  toggleTheme: () => get().setTheme(get().theme === "dark" ? "light" : "dark"),

  setLocale: (locale) => {
    document.documentElement.lang = locale === "en" ? "en" : "zh-CN";
    writeStored(storageKeys.locale, locale);
    void i18n.changeLanguage(locale);
    set({ locale });
  },

  setSidebarCollapsed: (collapsed) => {
    writeStored(storageKeys.sidebarCollapsed, collapsed ? "1" : "0");
    set({ sidebarCollapsed: collapsed });
  },

  toggleSidebar: () => get().setSidebarCollapsed(!get().sidebarCollapsed),

  setMobileNavOpen: (open) => set({ mobileNavOpen: open }),
}));
