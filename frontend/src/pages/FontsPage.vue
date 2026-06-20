<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from "vue";
import { useFamilyFiltersStore } from "@/stores/familyFilters";
import FontsToolbar, {
  type FontLayout,
} from "@/components/fonts/FontsToolbar.vue";
import FontFamilyList from "@/components/fonts/FontFamilyList.vue";

const filtersStore = useFamilyFiltersStore();

const fontSize = ref(40);
const lineHeight = ref(1.1);
const letterSpacing = ref(0);
const layout = ref<FontLayout>("specimen");

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
      class="pointer-events-none absolute inset-x-0 top-[60px] z-10 h-7 bg-gradient-to-b from-background to-transparent"
    />

    <!-- Liste -->
    <div class="scrollbar-thin absolute inset-0 overflow-y-auto">
      <div class="pb-16 pt-[72px]">
        <FontFamilyList :typo="typo" :layout="layout" />
      </div>
    </div>
  </div>
</template>
