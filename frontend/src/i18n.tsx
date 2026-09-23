"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { messages, type Language, type Translate } from "./messages";

const storageKey = "hackalem-language";
const locales: Record<Language, string> = { ru: "ru-RU", kk: "kk-KZ", en: "en-GB" };
const languages: { code: Language; label: string; short: string }[] = [
  { code: "ru", label: "Русский", short: "RU" },
  { code: "kk", label: "Қазақша", short: "ҚАЗ" },
  { code: "en", label: "English", short: "EN" },
];

function initialLanguage(): Language {
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved === "ru" || saved === "kk" || saved === "en") return saved;
  } catch {
    // The language switcher also works when browser storage is unavailable.
  }
  return "ru";
}

type LanguageContextValue = {
  language: Language;
  setLanguage: (language: Language) => void;
  locale: string;
  t: Translate;
  formatPower: (value: number) => string;
};
const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(initialLanguage);
  const locale = locales[language];
  const t: Translate = (key) => messages[key][language];
  // Preserve every decimal digit returned by the API, including very small values.
  const decimal = new Intl.NumberFormat(locale).formatToParts(1.1).find((part) => part.type === "decimal")?.value ?? ".";
  const formatPower = (value: number) => value.toString().replace(".", decimal);

  useEffect(() => {
    document.documentElement.lang = language;
    document.title = "ALT Energy";
    document.querySelector('meta[name="description"]')?.setAttribute("content", messages["Почасовой прогноз нормализованной мощности двух турбин на 24 и 48 часов с источником архивной погоды."][language]);
    try {
      localStorage.setItem(storageKey, language);
    } catch {
      // Persistence is optional; changing the interface language is not.
    }
  }, [language]);

  return <LanguageContext.Provider value={{ language, setLanguage, locale, t, formatPower }}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) throw new Error("LanguageProvider is required");
  return context;
}

export function LanguageSwitcher() {
  const { language, setLanguage, t } = useLanguage();
  return (
    <div className="language-switcher" role="group" aria-label={t("Язык интерфейса")}>
      {languages.map(({ code, label, short }) => (
        <button key={code} type="button" lang={code} aria-label={label} title={label} aria-pressed={language === code} onClick={() => setLanguage(code)}>{short}</button>
      ))}
    </div>
  );
}
