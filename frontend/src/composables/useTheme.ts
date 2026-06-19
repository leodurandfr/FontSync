import { ref } from "vue";

export type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "fontsync_theme";

// État singleton : partagé entre tous les composants qui appellent useTheme().
const theme = ref<Theme>(readStoredTheme());

let mediaQuery: MediaQueryList | null = null;

function readStoredTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") {
    return stored;
  }
  return "system";
}

function systemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

/** Applique le thème courant en (dé)posant la classe `.dark` sur <html>. */
function applyTheme(value: Theme) {
  const isDark = value === "dark" || (value === "system" && systemPrefersDark());
  document.documentElement.classList.toggle("dark", isDark);
}

function setTheme(value: Theme) {
  theme.value = value;
  localStorage.setItem(STORAGE_KEY, value);
  applyTheme(value);
}

/**
 * Initialise le thème au démarrage de l'app : applique la valeur mémorisée et
 * suit les changements de préférence système tant que le mode `system` est actif.
 */
function initTheme() {
  applyTheme(theme.value);
  if (!mediaQuery) {
    mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    mediaQuery.addEventListener("change", () => {
      if (theme.value === "system") applyTheme("system");
    });
  }
}

export function useTheme() {
  return { theme, setTheme, initTheme };
}
