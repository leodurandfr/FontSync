<script setup lang="ts">
import { ref, watch, onMounted } from "vue";
import { usePreviewTextStore } from "@/stores/previewText";

// Le texte affiché vient du store partagé : éditer ici met à jour toutes les
// previews. `placeholder` (nom de la famille) s'affiche quand le texte est vide.
const props = defineProps<{
  placeholder?: string;
}>();

const store = usePreviewTextStore();

const el = ref<HTMLElement | null>(null);
const focused = ref(false);

// Synchronise le DOM avec le store sans déplacer le curseur inutilement.
function syncDom() {
  if (el.value && el.value.innerText !== store.text) {
    el.value.innerText = store.text;
  }
}

onMounted(syncDom);

// Quand le texte change ailleurs, on reflète la modification — sauf si CET
// élément est en cours d'édition (réécrire son DOM ferait sauter le curseur).
watch(
  () => store.text,
  () => {
    if (!focused.value) syncDom();
  },
);

function onInput() {
  if (el.value) store.setText(el.value.innerText);
}

function onFocus() {
  focused.value = true;
}

function onBlur() {
  focused.value = false;
  syncDom();
}

function onKeydown(e: KeyboardEvent) {
  // Entrée valide (pas de retour à la ligne) ; Échap rend le focus.
  if (e.key === "Enter" || e.key === "Escape") {
    e.preventDefault();
    el.value?.blur();
  }
}

// Permet au parent de mesurer la position du mot (alignement du crossfade).
defineExpose({ getEl: () => el.value });
</script>

<template>
  <div
    ref="el"
    contenteditable="plaintext-only"
    spellcheck="false"
    role="textbox"
    :aria-label="placeholder"
    :data-placeholder="placeholder"
    class="editable-preview cursor-text outline-none"
    @input="onInput"
    @focus="onFocus"
    @blur="onBlur"
    @keydown="onKeydown"
  />
</template>

<style scoped>
.editable-preview:empty::before {
  content: attr(data-placeholder);
  opacity: 0.4;
  pointer-events: none;
}
</style>
