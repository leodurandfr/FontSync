import { readonly, ref } from "vue";

// En dessous de cette largeur de fenêtre (px), la sidebar repasse en overlay
// (drawer au-dessus du contenu, avec backdrop) au lieu de pousser le contenu
// (modèle Finder). Au-dessus, elle pousse le contenu et élargit la fenêtre
// native si besoin (cf. stores/layout → ensureWindowWidth).
export const SIDEBAR_OVERLAY_BELOW = 740;

// `matchMedia` plutôt qu'un listener `resize` : pas de polling, l'événement ne
// se déclenche qu'au franchissement du seuil. Singleton de module : une seule
// MQL partagée par tous les consommateurs (composants + store).
const mql = window.matchMedia(`(max-width: ${SIDEBAR_OVERLAY_BELOW - 1}px)`);
const overlay = ref(mql.matches);
mql.addEventListener("change", (e) => {
  overlay.value = e.matches;
});

/** Lecture impérative (hors réactivité Vue), pour le store Pinia. */
export function isSidebarOverlay(): boolean {
  return mql.matches;
}

/** Réactif : vrai quand la sidebar doit s'afficher en overlay (fenêtre étroite). */
export function useSidebarMode() {
  return { isOverlay: readonly(overlay) };
}
