<script setup lang="ts">
import { ref, watch } from "vue";
import { Search } from "lucide-vue-next";
import { Input } from "@/components/ui/input";
import { useFiltersStore } from "@/stores/filters";
import FilterPanel from "@/components/fonts/FilterPanel.vue";
import PreviewToolbar from "@/components/fonts/PreviewToolbar.vue";
import FontGrid from "@/components/fonts/FontGrid.vue";

const filtersStore = useFiltersStore();
const previewText = ref("Portez ce vieux whisky au juge blond qui fume");

const searchInput = ref(filtersStore.search);
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

watch(searchInput, (val) => {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    filtersStore.search = val;
  }, 300);
});
</script>

<template>
  <div class="flex h-full overflow-hidden">
    <FilterPanel />

    <main class="flex-1 overflow-y-auto p-6">
      <div class="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 class="text-3xl font-bold tracking-tight">Polices</h1>
          <p class="text-muted-foreground mt-1">
            Parcourez et gérez votre bibliothèque de polices.
          </p>
        </div>
        <div class="relative shrink-0 mt-1">
          <Search class="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            v-model="searchInput"
            type="search"
            placeholder="Rechercher une police..."
            class="pl-9 h-9 w-64"
          />
        </div>
      </div>

      <PreviewToolbar v-model="previewText" />
      <FontGrid :preview-text="previewText" />
    </main>
  </div>
</template>
