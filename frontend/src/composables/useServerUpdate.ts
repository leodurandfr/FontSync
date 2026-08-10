import { ref } from "vue";
import { apiFetch } from "@/lib/api";
import type { SystemInfo } from "@/types/api";

/**
 * Version du serveur, et mise à jour à la demande.
 *
 * La subtilité est dans l'attente. Mettre à jour fait **recréer le conteneur
 * qui est en train de répondre** : la requête peut mourir sans réponse, et un
 * échec réseau est ici le signe normal que ça marche. On ne juge donc pas sur
 * la réponse mais sur le retour de `/health`, puis on relit la version pour
 * dire si elle a bougé — sans quoi l'utilisateur n'a aucun moyen de savoir si
 * le serveur était déjà à jour.
 */

const HEALTH_POLL_MS = 2000;
const HEALTH_TIMEOUT_MS = 180_000;

export type UpdateState =
  "idle" | "requesting" | "restarting" | "done" | "error";

export function useServerUpdate() {
  const info = ref<SystemInfo | null>(null);
  const state = ref<UpdateState>("idle");
  const error = ref<string | null>(null);
  /** Vrai quand le serveur est revenu sur la même version : rien à mettre à jour. */
  const alreadyUpToDate = ref(false);

  async function fetchInfo(): Promise<SystemInfo | null> {
    try {
      const res = await apiFetch("/api/system/info");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      info.value = (await res.json()) as SystemInfo;
      return info.value;
    } catch {
      // Réglages secondaires : un échec ici ne doit pas casser la page.
      return null;
    }
  }

  function sleep(ms: number) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /** Attend que `/health` réponde à nouveau. `/health` est public : pas de token. */
  async function waitForRestart(): Promise<boolean> {
    const deadline = Date.now() + HEALTH_TIMEOUT_MS;
    while (Date.now() < deadline) {
      await sleep(HEALTH_POLL_MS);
      try {
        const res = await fetch("/health", { cache: "no-store" });
        if (res.ok) return true;
      } catch {
        // Serveur en cours de remplacement : c'est attendu, on repasse.
      }
    }
    return false;
  }

  async function update() {
    error.value = null;
    alreadyUpToDate.value = false;
    const before = info.value?.version ?? null;
    state.value = "requesting";

    try {
      const res = await apiFetch("/api/system/update", { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `HTTP ${res.status}`);
      }
    } catch (e) {
      // Une requête coupée n'est pas un échec : le conteneur a pu être recréé
      // avant de répondre. On tranche sur le retour de /health, pas ici.
      if (e instanceof TypeError) {
        state.value = "restarting";
      } else {
        state.value = "error";
        error.value = e instanceof Error ? e.message : String(e);
        return;
      }
    }

    state.value = "restarting";
    const back = await waitForRestart();
    if (!back) {
      state.value = "error";
      error.value = "timeout";
      return;
    }

    const after = await fetchInfo();
    alreadyUpToDate.value = after !== null && after.version === before;
    state.value = "done";
  }

  return { info, state, error, alreadyUpToDate, fetchInfo, update };
}
