import { ref, computed, watch } from "vue";
import { defineStore } from "pinia";
import { useFamiliesStore } from "./families";
import type { FamilyFilters } from "@/types/api";

export const useFamilyFiltersStore = defineStore("familyFilters", () => {
  const search = ref("");
  const classification = ref<string | undefined>();
  const sort = ref<FamilyFilters["sort"]>("name");
  const order = ref<FamilyFilters["order"]>("asc");
  const perPage = ref(50);

  const activeCount = computed(() => {
    let count = 0;
    if (search.value) count++;
    if (classification.value) count++;
    return count;
  });

  function toFilters(): FamilyFilters {
    return {
      search: search.value || undefined,
      classification: classification.value,
      sort: sort.value,
      order: order.value,
      page: 1,
      perPage: perPage.value,
    };
  }

  function reset() {
    search.value = "";
    classification.value = undefined;
    sort.value = "name";
    order.value = "asc";
  }

  watch(
    [search, classification, sort, order],
    () => {
      const familiesStore = useFamiliesStore();
      familiesStore.fetchFamilies(toFilters());
    },
    { deep: true },
  );

  return {
    search,
    classification,
    sort,
    order,
    perPage,
    activeCount,
    toFilters,
    reset,
  };
});
