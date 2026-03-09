import { ref, computed } from "vue";
import { defineStore } from "pinia";
import type {
  FontFamily,
  FontFamilyListResponse,
  FamilyFilters,
} from "@/types/api";

export const useFamiliesStore = defineStore("families", () => {
  const families = ref<FontFamily[]>([]);
  const total = ref(0);
  const page = ref(1);
  const pages = ref(0);
  const perPage = ref(50);
  const loading = ref(false);
  const loadingMore = ref(false);
  const error = ref<string | null>(null);
  const initialized = ref(false);

  let abortController: AbortController | null = null;

  const isEmpty = computed(
    () => initialized.value && families.value.length === 0 && !loading.value,
  );
  const hasMore = computed(() => page.value < pages.value);

  function buildParams(filters?: FamilyFilters): URLSearchParams {
    const params = new URLSearchParams();
    if (filters?.search) params.set("search", filters.search);
    if (filters?.classification)
      params.set("classification", filters.classification);
    if (filters?.sort) params.set("sort", filters.sort);
    if (filters?.order) params.set("order", filters.order);
    if (filters?.page) params.set("page", String(filters.page));
    if (filters?.perPage) params.set("per_page", String(filters.perPage));
    return params;
  }

  async function fetchFamilies(filters?: FamilyFilters) {
    abortController?.abort();
    abortController = new AbortController();
    const signal = abortController.signal;

    loading.value = true;
    error.value = null;
    try {
      const params = buildParams(filters);
      const res = await fetch(`/api/font-families?${params}`, { signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: FontFamilyListResponse = await res.json();

      families.value = data.items;
      total.value = data.total;
      page.value = data.page;
      pages.value = data.pages;
      perPage.value = data.perPage;
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      error.value = e instanceof Error ? e.message : "Erreur inconnue";
    } finally {
      loading.value = false;
      initialized.value = true;
    }
  }

  async function fetchMore(filters?: FamilyFilters) {
    if (!hasMore.value || loadingMore.value) return;
    loadingMore.value = true;
    error.value = null;
    try {
      const nextPage = page.value + 1;
      const params = buildParams({ ...filters, page: nextPage });
      const res = await fetch(`/api/font-families?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: FontFamilyListResponse = await res.json();

      families.value = [...families.value, ...data.items];
      total.value = data.total;
      page.value = data.page;
      pages.value = data.pages;
    } catch (e) {
      error.value = e instanceof Error ? e.message : "Erreur inconnue";
    } finally {
      loadingMore.value = false;
    }
  }

  function addFamily(family: FontFamily) {
    const exists = families.value.find((f) => f.id === family.id);
    if (!exists) {
      families.value.unshift(family);
      total.value++;
    }
  }

  function removeFamily(familyId: string) {
    families.value = families.value.filter((f) => f.id !== familyId);
    total.value = Math.max(0, total.value - 1);
  }

  function updateFamily(familyId: string, data: Partial<FontFamily>) {
    const idx = families.value.findIndex((f) => f.id === familyId);
    const existing = families.value[idx];
    if (existing) {
      families.value[idx] = { ...existing, ...data };
    }
  }

  return {
    families,
    total,
    page,
    pages,
    perPage,
    loading,
    loadingMore,
    error,
    initialized,
    isEmpty,
    hasMore,
    fetchFamilies,
    fetchMore,
    addFamily,
    removeFamily,
    updateFamily,
  };
});
