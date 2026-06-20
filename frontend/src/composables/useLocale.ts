import { computed } from "vue";
import { i18n, persistLocale, SUPPORTED_LOCALES, type Locale } from "@/i18n";

/**
 * Gestion de la langue de l'interface : lit/écrit la locale de vue-i18n et la
 * mémorise dans le navigateur. État partagé via l'instance i18n singleton.
 */
export function useLocale() {
  const locale = computed<Locale>({
    get: () => i18n.global.locale.value as Locale,
    set: (value) => setLocale(value),
  });

  function setLocale(value: Locale) {
    i18n.global.locale.value = value;
    persistLocale(value);
    document.documentElement.setAttribute("lang", value);
  }

  /** Tag BCP-47 pour `toLocaleDateString` et autres API Intl. */
  const dateLocale = computed(() =>
    locale.value === "fr" ? "fr-FR" : "en-US",
  );

  return { locale, setLocale, dateLocale, locales: SUPPORTED_LOCALES };
}
