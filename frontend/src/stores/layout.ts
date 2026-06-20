import { ref } from "vue";
import { defineStore } from "pinia";
import { ensureWindowWidth } from "@/composables/useWindowControls";
import { isSidebarOverlay } from "@/composables/useSidebarMode";

const WIDTH_KEY = "fontsync_sidebar_width";
const OPEN_KEY = "fontsync_sidebar_open";

const MIN_WIDTH = 180;
const MAX_WIDTH = 360;

// Gouttière autour du panneau (m-3 : 12px de chaque côté) ajoutée à la largeur
// occupée par la sidebar quand elle pousse le contenu.
const GUTTER = 24;

// Largeur minimale qu'on veut préserver pour la zone de contenu. À l'ouverture,
// si la fenêtre est trop étroite pour loger sidebar + ce minimum, on demande au
// natif de l'agrandir (modèle Finder). En navigateur, simple push.
const MIN_CONTENT = 640;

function clampWidth(w: number): number {
  return Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, w));
}

/** État de la coquille (sidebar) — persistant entre sessions via localStorage. */
export const useLayoutStore = defineStore("layout", () => {
  const sidebarOpen = ref(localStorage.getItem(OPEN_KEY) !== "false");
  const sidebarWidth = ref(
    clampWidth(Number(localStorage.getItem(WIDTH_KEY)) || 220),
  );

  function setSidebarOpen(value: boolean, persist = true) {
    // À l'ouverture en mode « push » (fenêtre large), garantir que la fenêtre
    // native est assez large pour loger la sidebar sans écraser le contenu sous
    // MIN_CONTENT (no-op en navigateur). En mode overlay (fenêtre étroite), la
    // sidebar passe au-dessus du contenu : on n'élargit pas la fenêtre.
    if (value && !sidebarOpen.value && !isSidebarOverlay()) {
      ensureWindowWidth(sidebarWidth.value + GUTTER + MIN_CONTENT);
    }
    sidebarOpen.value = value;
    if (persist) localStorage.setItem(OPEN_KEY, String(value));
  }

  function toggleSidebar() {
    setSidebarOpen(!sidebarOpen.value);
  }

  function setSidebarWidth(value: number) {
    sidebarWidth.value = clampWidth(value);
    localStorage.setItem(WIDTH_KEY, String(sidebarWidth.value));
  }

  return {
    sidebarOpen,
    sidebarWidth,
    minWidth: MIN_WIDTH,
    maxWidth: MAX_WIDTH,
    gutter: GUTTER,
    setSidebarOpen,
    toggleSidebar,
    setSidebarWidth,
  };
});
