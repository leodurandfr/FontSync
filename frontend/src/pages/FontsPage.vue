<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from "vue";
import { storeToRefs } from "pinia";
import { useFamilyFiltersStore } from "@/stores/familyFilters";
import { useFontsViewStore } from "@/stores/fontsView";
import FontsToolbar from "@/components/fonts/FontsToolbar.vue";
import FontFamilyList from "@/components/fonts/FontFamilyList.vue";

const filtersStore = useFamilyFiltersStore();

// Réglages d'affichage persistés dans un store : ils survivent à l'aller-retour
// vers le détail d'une fonte (sinon le layout retomberait sur « specimen »).
const { layout, fontSize, lineHeight, letterSpacing } = storeToRefs(
  useFontsViewStore(),
);

const typo = computed(() => ({
  fontSize: fontSize.value,
  lineHeight: lineHeight.value,
  letterSpacing: letterSpacing.value,
}));

// Recherche : on débounce la frappe vers le store (qui relance le fetch).
const searchInput = ref(filtersStore.search);
let debounceTimer: ReturnType<typeof setTimeout> | null = null;
watch(searchInput, (val) => {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    filtersStore.search = val;
  }, 300);
});
onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer);
});
</script>

<template>
  <div class="relative h-full">
    <!-- Toolbar flottante -->
    <div class="absolute left-3 right-3 top-3 z-20">
      <FontsToolbar
        v-model:font-size="fontSize"
        v-model:line-height="lineHeight"
        v-model:letter-spacing="letterSpacing"
        v-model:layout="layout"
        v-model:search="searchInput"
      />
    </div>

    <!-- Fade sous la toolbar -->
    <div
      class="pointer-events-none absolute left-0 right-3 top-[60px] z-10 h-10 bg-gradient-to-b from-background/75 to-transparent"
    />

    <!-- Liste -->
    <div class="scrollbar-thin absolute inset-x-0 bottom-0 top-[60px] overflow-y-auto">
      <div class="pb-16 pt-3">
        <FontFamilyList :typo="typo" :layout="layout" />
      </div>
    </div>
  </div>
</template>
