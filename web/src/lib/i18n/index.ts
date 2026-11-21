import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import enChat from "@/locales/en/chat.json";
import enCommon from "@/locales/en/common.json";
import enDesign from "@/locales/en/design.json";
import enHome from "@/locales/en/home.json";
import enSettings from "@/locales/en/settings.json";
import enSetup from "@/locales/en/setup.json";
import zhChat from "@/locales/zh/chat.json";
import zhCommon from "@/locales/zh/common.json";
import zhDesign from "@/locales/zh/design.json";
import zhHome from "@/locales/zh/home.json";
import zhSettings from "@/locales/zh/settings.json";
import zhSetup from "@/locales/zh/setup.json";

import { readStored, storageKeys } from "../storage";

export const locales = ["en", "zh"] as const;
export type AppLocale = (typeof locales)[number];
export const defaultLocale: AppLocale = "zh";

const resources = {
  en: {
    common: enCommon,
    chat: enChat,
    home: enHome,
    settings: enSettings,
    setup: enSetup,
    design: enDesign,
  },
  zh: {
    common: zhCommon,
    chat: zhChat,
    home: zhHome,
    settings: zhSettings,
    setup: zhSetup,
    design: zhDesign,
  },
} as const;

function initialLocale(): AppLocale {
  const stored = readStored(storageKeys.locale);
  if (stored === "en" || stored === "zh") return stored;
  const fromNavigator = navigator.language.toLowerCase();
  return fromNavigator.startsWith("zh") ? "zh" : "en";
}

void i18n.use(initReactI18next).init({
  resources,
  lng: initialLocale(),
  fallbackLng: defaultLocale,
  defaultNS: "common",
  ns: ["common", "chat", "home", "settings", "setup", "design"],
  interpolation: { escapeValue: false },
  returnNull: false,
});

export default i18n;
