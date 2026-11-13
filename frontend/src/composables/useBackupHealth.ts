import { computed, ref } from "vue";
import { apiFetch } from "@/lib/api";
import type { BackupHealth } from "@/types/api";

/**
 * État des sauvegardes automatiques du serveur.
 *
 * Une sauvegarde qui échoue en silence ne se découvre que le jour où l'on en
 * a besoin : Réglages → Serveur affiche donc la date du dernier instantané et
 * avertit dès qu'il manque quelque chose.
 */

export type BackupWarning = "stale" | "error" | "mirror" | null;

/**
 * L'avertissement à afficher, s'il y en a un. Le retard prime (rien de récent
 * à restaurer), puis l'erreur, puis le miroir incomplet.
 */
export function backupWarning(health: BackupHealth | null): BackupWarning {
  if (!health || !health.enabled) return null;
  if (health.stale) return "stale";
  if (health.lastError) return "error";
  if ((health.mirrorFailed ?? 0) > 0) return "mirror";
  return null;
}

export function useBackupHealth() {
  const health = ref<BackupHealth | null>(null);

  async function fetchHealth(): Promise<BackupHealth | null> {
    try {
      const res = await apiFetch("/api/system/backups");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      health.value = (await res.json()) as BackupHealth;
      return health.value;
    } catch {
      // Serveur plus ancien (route absente) ou réseau : la section se masque.
      return null;
    }
  }

  const warning = computed(() => backupWarning(health.value));

  return { health, warning, fetchHealth };
}
