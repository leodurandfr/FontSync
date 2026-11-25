import { ref } from "vue";

export type Theme = "light" | "dark" | "system";

/**
 * Palette de couleurs : duo contrasté (sidebar colorée, fond, accent
 * complémentaire) appliqué à toute l'interface. `neutral` = l'interface noir et blanc
 * d'origine. Les teintes vivent dans `assets/index.css` (`[data-palette]`).
 */
export const PALETTES = [
  "neutral",
  "navy",
  "forest",
  "plum",
  "cobalt",
  "flamingo",
] as const;
export type Palette = (typeof PALETTES)[number];

/** Couleurs montrées par la pastille : sidebar, fond, accent. */
export const PALETTE_SWATCH: Record<
  Palette,
  { sidebar: string; bg: string; accent: string }
> = {
  neutral: { sidebar: "#ffffff", bg: "#e9eaec", accent: "#111111" },
  navy: { sidebar: "#1b2a4a", bg: "#f4efe6", accent: "#ff6b4a" },
  forest: { sidebar: "#1f3d2b", bg: "#f2e8d5", accent: "#e0a020" },
  plum: { sidebar: "#3b1f4a", bg: "#efe8f5", accent: "#b8d430" },
  cobalt: { sidebar: "#1f4fd8", bg: "#fff1e3", accent: "#ff7a1a" },
  flamingo: { sidebar: "#e23d7a", bg: "#e6f5ec", accent: "#0f9d63" },
};

const STORAGE_KEY = "fontsync_theme";
const PALETTE_KEY = "fontsync_palette";

// État singleton : partagé entre tous les composants qui appellent useTheme().
const theme = ref<Theme>(readStoredTheme());
const palette = ref<Palette>(readStoredPalette());
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

function readStoredPalette(): Palette {
  const stored = readStorage(PALETTE_KEY);
  return (PALETTES as readonly string[]).includes(stored ?? "")
    ? (stored as Palette)
    : "neutral";
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

/** Pose `data-palette` sur <html> (absent pour la palette neutre). */
function applyPalette(value: Palette) {
  const root = document.documentElement;
  if (value === "neutral") root.removeAttribute("data-palette");
  else root.setAttribute("data-palette", value);
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

function setPalette(value: Palette) {
  palette.value = value;
  writeStorage(PALETTE_KEY, value);
  applyPalette(value);
}

/**
 * Initialise le thème au démarrage de l'app : applique la valeur mémorisée et
 * suit les changements de préférence système tant que le mode `system` est actif.
 */
function initTheme() {
  applyTheme(theme.value);
  applyPalette(palette.value);
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
    palette,
    setTheme,
    toggleTheme,
    setPalette,
    initTheme,
    dark,
  };
}
