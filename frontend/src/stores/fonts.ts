import { ref, computed } from "vue";
import { defineStore } from "pinia";
import { apiFetch } from "@/lib/api";
import type {
  Font,
  FontListResponse,
  FontUploadResponse,
  FontFilters,
} from "@/types/api";

export const useFontsStore = defineStore("fonts", () => {
  const fonts = ref<Font[]>([]);
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
    () => initialized.value && fonts.value.length === 0 && !loading.value,
  );
  const hasMore = computed(() => page.value < pages.value);

  function buildParams(filters?: FontFilters): URLSearchParams {
    const params = new URLSearchParams();
    if (filters?.search) params.set("search", filters.search);
    if (filters?.classification)
      params.set("classification", filters.classification);
    if (filters?.format) params.set("file_format", filters.format);
    if (filters?.isVariable !== undefined)
      params.set("is_variable", String(filters.isVariable));
    if (filters?.weightMin !== undefined)
      params.set("weight_min", String(filters.weightMin));
    if (filters?.weightMax !== undefined)
      params.set("weight_max", String(filters.weightMax));
    if (filters?.familyId) params.set("family_id", filters.familyId);
    if (filters?.orphan !== undefined)
      params.set("orphan", String(filters.orphan));
    if (filters?.sort) params.set("sort", filters.sort);
    if (filters?.order) params.set("order", filters.order);
    if (filters?.page) params.set("page", String(filters.page));
    if (filters?.perPage) params.set("per_page", String(filters.perPage));
    if (filters?.scripts) {
      for (const s of filters.scripts) params.append("scripts", s);
    }
    return params;
  }

  async function fetchFonts(filters?: FontFilters) {
    abortController?.abort();
    abortController = new AbortController();
    const signal = abortController.signal;

    loading.value = true;
    error.value = null;
    try {
      const params = buildParams(filters);
      const res = await apiFetch(`/api/fonts?${params}`, { signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: FontListResponse = await res.json();

      fonts.value = data.items;
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

  async function fetchMore(filters?: FontFilters) {
    if (!hasMore.value || loadingMore.value) return;
    loadingMore.value = true;
    error.value = null;
    try {
      const nextPage = page.value + 1;
      const params = buildParams({ ...filters, page: nextPage });
      const res = await apiFetch(`/api/fonts?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: FontListResponse = await res.json();

      fonts.value = [...fonts.value, ...data.items];
      total.value = data.total;
      page.value = data.page;
      pages.value = data.pages;
    } catch (e) {
      error.value = e instanceof Error ? e.message : "Erreur inconnue";
    } finally {
      loadingMore.value = false;
    }
  }

  async function uploadFonts(files: File[]): Promise<FontUploadResponse> {
    const form = new FormData();
    for (const file of files) form.append("files", file);

    const res = await apiFetch("/api/fonts/upload", {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    // Les fonts importées arrivent aussi via l'event WS `font.added` ;
    // `addFont` est idempotent (dédup par id) donc pas de doublon.
    return (await res.json()) as FontUploadResponse;
  }

  /**
   * Met une police à la corbeille (`DELETE /api/fonts/{id}`). Côté serveur
   * c'est une intention récupérable depuis la Corbeille, pas un effacement.
   * Lève une `Error` portant le `detail` du serveur en cas de refus.
   */
  async function trashFont(fontId: string): Promise<void> {
    const res = await apiFetch(`/api/fonts/${fontId}`, { method: "DELETE" });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      throw new Error(data?.detail ?? `HTTP ${res.status}`);
    }
    removeFonts([fontId]);
  }

  function addFont(font: Font) {
    const exists = fonts.value.find((f) => f.id === font.id);
    if (!exists) {
      fonts.value.unshift(font);
      total.value++;
    }
  }

  // Délègue à `removeFonts` (idempotent) : après `trashFont`, l'event WS
  // `font.deleted` arrive pour une police déjà retirée — le total ne doit
  // baisser qu'une fois.
  function removeFont(fontId: string) {
    removeFonts([fontId]);
  }

  /** Retire plusieurs polices en une passe (quarantaine : `fonts.deleted`). */
  function removeFonts(fontIds: string[]) {
    const ids = new Set(fontIds);
    if (ids.size === 0) return;
    const before = fonts.value.length;
    fonts.value = fonts.value.filter((f) => !ids.has(f.id));
    // Seules les polices réellement retirées comptent : un id déjà retiré
    // (font.deleted antérieur) ou hors des filtres de la liste ne doit pas
    // faire baisser son total.
    total.value = Math.max(0, total.value - (before - fonts.value.length));
  }

  function updateFont(fontId: string, data: Partial<Font>) {
    const idx = fonts.value.findIndex((f) => f.id === fontId);
    const existing = fonts.value[idx];
    if (existing) {
      fonts.value[idx] = { ...existing, ...data };
    }
  }

  return {
    fonts,
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
    fetchFonts,
    fetchMore,
    uploadFonts,
    trashFont,
    addFont,
    removeFont,
    removeFonts,
    updateFont,
  };
});
