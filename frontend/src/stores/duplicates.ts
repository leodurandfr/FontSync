import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { apiFetch } from "@/lib/api";
import type {
  DuplicateFaceGroup,
  DuplicateFacesResponse,
  ResolveDuplicatesResponse,
} from "@/types/api";

/**
 * Doublons de face : la même police sous plusieurs noms, donc plusieurs
 * empreintes — ce que la déduplication à l'import ne peut pas voir.
 *
 * Le geste que cet écran propose est **en bloc**, et c'est délibéré : une
 * bibliothèque réelle en compte près d'un millier, et les réviser un par un se
 * compterait en heures. Ce que l'utilisateur révise, c'est le résultat de la
 * règle — un gardé par face, le plus complet — pas chaque groupe. Deux choses
 * rendent ça tenable, et il faut les garder en tête en touchant à ce store :
 *
 * - `exclude` retire des faces du geste, plutôt que d'exiger de les cocher une
 *   à une. On part de « tout », on retranche ce qu'on veut garder ;
 * - rien n'est effacé : les fichiers partent en corbeille, d'où ils reviennent
 *   d'un clic tant qu'elle n'a pas été vidée.
 */
export const useDuplicatesStore = defineStore("duplicates", () => {
  const items = ref<DuplicateFaceGroup[]>([]);
  const totalGroups = ref(0);
  const totalRedundant = ref(0);
  const bytesFreed = ref(0);
  const scanned = ref(0);
  const loading = ref(false);
  const resolving = ref(false);
  const error = ref<string | null>(null);
  const initialized = ref(false);

  /** Faces que l'utilisateur a retirées du geste. */
  const excluded = ref<Set<string>>(new Set());

  const isEmpty = computed(
    () => initialized.value && totalGroups.value === 0 && !loading.value,
  );

  const selected = computed(() =>
    items.value.filter((g) => !excluded.value.has(g.key)),
  );

  /**
   * Ce que le geste retirerait *réellement*, une fois les exclusions faites.
   *
   * Tant que rien n'est exclu, on renvoie les totaux du serveur : ils portent
   * sur tout le recensement, alors que `items` n'est qu'une page. Dès qu'une
   * exclusion existe, la page devient la seule chose qu'on sache compter — le
   * geste est alors restreint à elle, cf. `resolve`.
   */
  const pendingCount = computed(() =>
    excluded.value.size === 0
      ? totalRedundant.value
      : selected.value.reduce((n, g) => n + g.redundant.length, 0),
  );

  const pendingBytes = computed(() =>
    excluded.value.size === 0
      ? bytesFreed.value
      : selected.value.reduce((n, g) => n + g.bytesFreed, 0),
  );

  async function fetchDuplicates(perPage = 200) {
    loading.value = true;
    error.value = null;
    try {
      const res = await apiFetch(`/api/fonts/duplicates?per_page=${perPage}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: DuplicateFacesResponse = await res.json();
      items.value = data.items;
      totalGroups.value = data.totalGroups;
      totalRedundant.value = data.totalRedundant;
      bytesFreed.value = data.bytesFreed;
      scanned.value = data.scanned;
      excluded.value = new Set();
    } catch (e) {
      error.value = e instanceof Error ? e.message : "Erreur inconnue";
    } finally {
      loading.value = false;
      initialized.value = true;
    }
  }

  function toggleExcluded(key: string) {
    const next = new Set(excluded.value);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    excluded.value = next;
  }

  /**
   * Envoie les fichiers en trop à la corbeille.
   *
   * Sans exclusion, on laisse le serveur traiter **tout** le recensement plutôt
   * que d'énumérer les clés d'une page : sinon le geste ne porterait que sur
   * les 200 premières faces sans le dire, ce qui ressemblerait à un bug.
   */
  async function resolve(): Promise<ResolveDuplicatesResponse> {
    resolving.value = true;
    error.value = null;
    try {
      const body =
        excluded.value.size === 0
          ? {}
          : { keys: selected.value.map((g) => g.key) };
      const res = await apiFetch("/api/fonts/duplicates/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail ?? `HTTP ${res.status}`);
      }
      const outcome: ResolveDuplicatesResponse = await res.json();
      await fetchDuplicates();
      return outcome;
    } finally {
      resolving.value = false;
    }
  }

  return {
    items,
    totalGroups,
    totalRedundant,
    bytesFreed,
    scanned,
    loading,
    resolving,
    error,
    initialized,
    excluded,
    isEmpty,
    selected,
    pendingCount,
    pendingBytes,
    fetchDuplicates,
    toggleExcluded,
    resolve,
  };
});
