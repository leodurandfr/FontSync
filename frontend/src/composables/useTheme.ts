import { ref } from "vue";

export type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "fontsync_theme";

// État singleton : partagé entre tous les composants qui appellent useTheme().
const theme = ref<Theme>(readStoredTheme());
/** Apparence réellement affichée (le mode `system` résolu). */
const dark = ref(false);

let mediaQuery: MediaQueryList | null = null;

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Stockage indisponible (navigation privée) : le choix vaut pour la session.
  }
}

function readStoredTheme(): Theme {
  const stored = readStorage(STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") {
    return stored;
  }
  return "system";
}

function systemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function isDarkTheme(value: Theme): boolean {
  return value === "dark" || (value === "system" && systemPrefersDark());
}

/** Applique le thème courant en (dé)posant la classe `.dark` sur <html>. */
function applyTheme(value: Theme) {
  dark.value = isDarkTheme(value);
  document.documentElement.classList.toggle("dark", dark.value);
}

function setTheme(value: Theme) {
  theme.value = value;
  writeStorage(STORAGE_KEY, value);
  applyTheme(value);
}

/** Bascule clair ↔ sombre à partir de l'apparence affichée (y compris en mode système). */
function toggleTheme() {
  setTheme(dark.value ? "light" : "dark");
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
  return {
    theme,
    setTheme,
    toggleTheme,
    initTheme,
    dark,
  };
}
