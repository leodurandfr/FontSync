import { ref } from "vue";
import { defineStore } from "pinia";
import type { FontLayout } from "@/components/fonts/types";

/**
 * Réglages d'affichage de la liste de fontes (layout + typo).
 *
 * Vit dans un store plutôt que dans `FontsPage` pour survivre à la navigation :
 * quand on ouvre le détail d'une fonte puis qu'on revient, la page est
 * remontée, mais le layout et les réglages typo choisis sont restaurés depuis
 * ici (au lieu de retomber sur l'état initial « specimen »).
 */
export const useFontsViewStore = defineStore("fontsView", () => {
  const layout = ref<FontLayout>("specimen");
  const fontSize = ref(40);
  const lineHeight = ref(1.1);
  const letterSpacing = ref(0);

  return { layout, fontSize, lineHeight, letterSpacing };
});
