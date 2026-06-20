import { defineStore } from "pinia";
import { ref } from "vue";

/**
 * Texte d'aperçu partagé par toutes les previews de fontes.
 *
 * Éditable en place depuis n'importe quel aperçu (voir `EditablePreview.vue`) ;
 * une modification s'applique instantanément à toutes les fontes affichées.
 */
export const usePreviewTextStore = defineStore("previewText", () => {
  const text = ref("The quick brown fox jumps over the lazy dog");

  function setText(value: string) {
    text.value = value;
  }

  return { text, setText };
});
