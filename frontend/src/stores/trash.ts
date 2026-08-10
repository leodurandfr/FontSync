import { ref, computed } from "vue";
import { defineStore } from "pinia";
import { apiFetch } from "@/lib/api";
import type { Font, TrashListResponse } from "@/types/api";

/**
 * Corbeille : les polices supprimées, et les deux gestes qui les concernent —
 * restaurer, ou vider (retirer le fichier du stockage).
 *
 * Vider ne supprime pas la ligne en base. C'est délibéré côté serveur :
 * l'empreinte doit survivre au fichier, sinon la police revient au premier push
 * d'une machine qui la détient encore. Conséquence visible ici : une police
 * `purgedAt` reste affichée mais n'est plus restaurable.
 */
export const useTrashStore = defineStore("trash", () => {
  const items = ref<Font[]>([]);
  const total = ref(0);
  const pendingConfirmation = ref(0);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const initialized = ref(false);

  const isEmpty = computed(
    () => initialized.value && items.value.length === 0 && !loading.value,
  );
  /** Polices dont la suppression attend un arbitrage (détection au-delà du seuil). */
  const pending = computed(() =>
    items.value.filter((f) => f.deletedReason === "quarantine_pending"),
  );

  async function fetchTrash() {
    loading.value = true;
    error.value = null;
    try {
      const res = await apiFetch("/api/fonts/trash?per_page=200");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: TrashListResponse = await res.json();
      items.value = data.items;
      total.value = data.total;
      pendingConfirmation.value = data.pendingConfirmation;
    } catch (e) {
      error.value = e instanceof Error ? e.message : "Erreur inconnue";
    } finally {
      loading.value = false;
      initialized.value = true;
    }
  }

  async function restore(fontId: string) {
    const res = await apiFetch(`/api/fonts/${fontId}/restore`, {
      method: "POST",
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      throw new Error(data?.detail ?? `HTTP ${res.status}`);
    }
    items.value = items.value.filter((f) => f.id !== fontId);
    total.value = Math.max(0, total.value - 1);
  }

  async function purge(fontId: string) {
    const res = await apiFetch(`/api/fonts/${fontId}/purge`, {
      method: "POST",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await fetchTrash();
  }

  async function emptyTrash() {
    const res = await apiFetch("/api/fonts/trash/empty", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await fetchTrash();
  }

  /** Lève la suspension : les appareils concernés désinstalleront ces polices. */
  async function confirmPending() {
    const res = await apiFetch("/api/fonts/trash/confirm", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await fetchTrash();
  }

  return {
    items,
    total,
    pendingConfirmation,
    loading,
    error,
    initialized,
    isEmpty,
    pending,
    fetchTrash,
    restore,
    purge,
    emptyTrash,
    confirmPending,
  };
});
