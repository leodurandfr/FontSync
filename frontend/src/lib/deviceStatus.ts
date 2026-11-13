import type { Device } from "@/types/api";

/**
 * Ligne d'état d'un appareil (Réglages → Appareils).
 *
 * « Connecté » ne veut pas dire « se synchronise » : le process `listen` peut
 * survivre à un job `sync` qui ne démarre plus (cas du Mac mini, M-39). Le
 * serveur signale ce retard (`syncOverdue`) ; un appareil connecté et en
 * retard s'affiche en ambre avec l'âge du dernier passage de l'agent. Hors
 * ligne, l'affichage ne change pas.
 */
export type DeviceStatusKind = "connected" | "overdue" | "offline";

export interface DeviceStatus {
  kind: DeviceStatusKind;
  text: string;
}

export type Translate = (
  key: string,
  params?: Record<string, unknown>,
) => string;

export function deviceStatusKind(
  online: boolean,
  syncOverdue: boolean | undefined,
): DeviceStatusKind {
  if (!online) return "offline";
  return syncOverdue ? "overdue" : "connected";
}

/** « il y a 32 h », « à l'instant »… en minuscules : s'insère dans une phrase. */
export function formatRelativeTime(
  dateStr: string | null,
  t: Translate,
  now: number = Date.now(),
): string {
  if (!dateStr) return t("devices.never");
  const diff = now - new Date(dateStr).getTime();
  if (diff < 60_000) return t("devices.justNow");
  if (diff < 3_600_000)
    return t("devices.minutesAgo", { n: Math.floor(diff / 60_000) });
  if (diff < 86_400_000)
    return t("devices.hoursAgo", { n: Math.floor(diff / 3_600_000) });
  return t("devices.daysAgo", { n: Math.floor(diff / 86_400_000) });
}

export function deviceStatus(
  device: Pick<Device, "lastSeenAt" | "syncOverdue">,
  online: boolean,
  t: Translate,
  now: number = Date.now(),
): DeviceStatus {
  const kind = deviceStatusKind(online, device.syncOverdue);
  if (kind === "connected") return { kind, text: t("devices.connected") };
  if (kind === "overdue") {
    return {
      kind,
      text: device.lastSeenAt
        ? t("devices.connectedOverdue", {
            time: formatRelativeTime(device.lastSeenAt, t, now),
          })
        : t("devices.connectedNeverSynced"),
    };
  }
  return {
    kind,
    text: t("devices.seenAgo", {
      time: formatRelativeTime(device.lastSeenAt, t, now),
    }),
  };
}
