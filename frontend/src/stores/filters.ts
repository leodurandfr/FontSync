import { ref, computed, watch } from "vue";
import { defineStore } from "pinia";
import { useFontsStore } from "./fonts";
import type { FontFilters } from "@/types/api";

export const useFiltersStore = defineStore("filters", () => {
  const search = ref("");
  const classification = ref<string | undefined>();
  const format = ref<string | undefined>();
  const scripts = ref<string[]>([]);
  const isVariable = ref<boolean | undefined>();
  const weightMin = ref<number | undefined>();
  const weightMax = ref<number | undefined>();
  const sort = ref<FontFilters["sort"]>("created_at");
  const order = ref<FontFilters["order"]>("desc");
  const perPage = ref(50);

  const activeCount = computed(() => {
    let count = 0;
    if (search.value) count++;
    if (classification.value) count++;
    if (format.value) count++;
    if (scripts.value.length > 0) count++;
    if (isVariable.value !== undefined) count++;
    if (weightMin.value !== undefined || weightMax.value !== undefined) count++;
    return count;
  });

  function toFilters(): FontFilters {
    return {
      search: search.value || undefined,
      classification: classification.value,
      format: format.value,
      scripts: scripts.value.length > 0 ? scripts.value : undefined,
      isVariable: isVariable.value,
      weightMin: weightMin.value,
      weightMax: weightMax.value,
      sort: sort.value,
      order: order.value,
      page: 1,
      perPage: perPage.value,
    };
  }

  function reset() {
    search.value = "";
    classification.value = undefined;
    format.value = undefined;
    scripts.value = [];
    isVariable.value = undefined;
    weightMin.value = undefined;
    weightMax.value = undefined;
    sort.value = "created_at";
    order.value = "desc";
  }

  // Auto-fetch quand les filtres changent (reset to page 1)
  watch(
    [
      search,
      classification,
      format,
      scripts,
      isVariable,
      weightMin,
      weightMax,
      sort,
      order,
    ],
    () => {
      const fontsStore = useFontsStore();
      fontsStore.fetchFonts(toFilters());
    },
    { deep: true },
  );

  return {
    search,
    classification,
    format,
    scripts,
    isVariable,
    weightMin,
    weightMax,
    sort,
    order,
    perPage,
    activeCount,
    toFilters,
    reset,
  };
});
