import { createI18n } from "vue-i18n";
import en from "./en";
import fr from "./fr";

export type Locale = "en" | "fr";

export const SUPPORTED_LOCALES: Locale[] = ["en", "fr"];
export const DEFAULT_LOCALE: Locale = "en";

const STORAGE_KEY = "fontsync_locale";

export function readStoredLocale(): Locale {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "en" || stored === "fr") return stored;
  return DEFAULT_LOCALE;
}

export function persistLocale(locale: Locale) {
  localStorage.setItem(STORAGE_KEY, locale);
}

/**
 * Français : 0 et 1 au singulier (« 0 fichier »). La règle par défaut de
 * vue-i18n met le pluriel dès que n ≠ 1, juste en anglais seulement. Pour un
 * message à trois formes, la sémantique par défaut (zéro | un | plusieurs)
 * est gardée.
 */
export function frenchPluralRule(
  choice: number,
  choicesLength: number,
): number {
  const n = Math.abs(choice);
  if (choicesLength === 3) return n === 0 ? 0 : n === 1 ? 1 : 2;
  return n <= 1 ? 0 : 1;
}

export const pluralRules = { fr: frenchPluralRule };

export const i18n = createI18n({
  legacy: false,
  locale: readStoredLocale(),
  fallbackLocale: DEFAULT_LOCALE,
  messages: { en, fr },
  pluralRules,
});
