<script setup lang="ts">
import { ref, computed } from "vue";
import { Monitor, Loader2 } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { apiFetch } from "@/lib/api";
import { useLocale } from "@/composables/useLocale";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

// Forme exacte renvoyée par `GET /api/fonts/{id}/devices` — un statut par
// police. Le sheet peut recevoir plusieurs `fontIds` (famille entière) : ces
// entrées sont agrégées par appareil en `DeviceStatus` ci-dessous.
interface RawDeviceStatus {
  deviceId: string;
  deviceName: string;
  hostname: string;
  isOnline: boolean;
  installed: boolean;
  localPath: string | null;
  installedAt: string | null;
  active: boolean;
}

interface DeviceStatus {
  deviceId: string;
  deviceName: string;
  hostname: string;
  isOnline: boolean;
  installed: boolean;
  installedAt: string | null;
  // Agrégats sur les styles de `fontIds` réellement installés sur cet
  // appareil : `active` — tous le sont ; `mixed` — certains seulement.
  active: boolean;
  mixed: boolean;
}

function mergeDeviceStatuses(perFont: RawDeviceStatus[][]): DeviceStatus[] {
  const byDevice = new Map<string, RawDeviceStatus[]>();
  for (const statuses of perFont) {
    for (const status of statuses) {
      const entries = byDevice.get(status.deviceId) ?? [];
      entries.push(status);
      byDevice.set(status.deviceId, entries);
    }
  }
  const merged: DeviceStatus[] = [];
  for (const entries of byDevice.values()) {
    const first = entries[0];
    if (!first) continue;
    const installedEntries = entries.filter((e) => e.installed);
    const activeCount = installedEntries.filter((e) => e.active).length;
    // Le plus récent : peu importe quel style précis, seule la présence compte.
    const installedDates = installedEntries
      .map((e) => e.installedAt)
      .filter((d): d is string => d != null)
      .sort();
    merged.push({
      deviceId: first.deviceId,
      deviceName: first.deviceName,
      hostname: first.hostname,
      isOnline: first.isOnline,
      installed: installedEntries.length > 0,
      installedAt: installedDates[installedDates.length - 1] ?? null,
      active:
        installedEntries.length > 0 && activeCount === installedEntries.length,
      mixed: activeCount > 0 && activeCount < installedEntries.length,
    });
  }
  return merged;
}

const props = defineProps<{
  fontIds: string[];
  triggerVariant?: "outline" | "ghost" | "icon";
  triggerLabel?: string;
}>();

const { t } = useI18n();
const { dateLocale } = useLocale();

const deviceStatuses = ref<DeviceStatus[]>([]);
const devicesLoading = ref(false);
const actionInProgress = ref<Set<string>>(new Set());
// Appareils dont l'installation a été demandée et dont macOS n'a pas encore fini
// de reconstruire son index (cf. `pendingDelays`).
const reindexing = ref<Set<string>>(new Set());

const isMultiFont = computed(() => props.fontIds.length > 1);

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString(dateLocale.value, {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function fetchDeviceStatuses() {
  devicesLoading.value = true;
  try {
    // Un appel par police (une famille entière peut en compter plusieurs) ;
    // même liste d'appareils partout, seul le statut d'installation varie.
    const responses = await Promise.all(
      props.fontIds.map((id) => apiFetch(`/api/fonts/${id}/devices`)),
    );
    const perFont: RawDeviceStatus[][] = [];
    for (const res of responses) {
      if (res.ok) perFont.push(await res.json());
    }
    deviceStatuses.value = mergeDeviceStatuses(perFont);
  } catch (e) {
    console.error("Failed to fetch device statuses:", e);
  } finally {
    devicesLoading.value = false;
  }
}

// Rythme de rafraîchissement du statut après une demande d'installation, en ms.
// L'installation n'est pas instantanée et ce n'est pas un défaut : le fichier
// est copié en quelques secondes, mais macOS 14+ ne le prend en compte qu'après
// avoir reconstruit son index de polices — quelques dizaines de secondes sur une
// grosse bibliothèque. Sans ces relances (et sans le message qui les accompagne),
// l'appareil reste affiché « non installée » et l'utilisateur conclut à un échec.
const pendingDelays = [3_000, 10_000, 25_000, 45_000, 75_000];

function markReindexing(deviceId: string, active: boolean) {
  const next = new Set(reindexing.value);
  if (active) next.add(deviceId);
  else next.delete(deviceId);
  reindexing.value = next;
}

// Stop-gap B1 : le modèle de sync est un *miroir* (l'appareil pulle les fonts du
// serveur selon `auto_pull`). « Installer » ne pousse donc pas une commande
// ciblée : il déclenche un re-sync de l'appareil. La désinstallation sélective
// par appareil reste reportée au redesign « manifeste désiré » — l'activation,
// elle, n'en a pas besoin (cf. `handleToggleActive` ci-dessous).
async function handleInstall(deviceId: string) {
  actionInProgress.value = new Set([...actionInProgress.value, deviceId]);
  try {
    // Un seul appel suffit : le re-sync récupère toutes les fonts manquantes.
    await apiFetch(`/api/fonts/${props.fontIds[0]}/install/${deviceId}`, {
      method: "POST",
    });
    markReindexing(deviceId, true);
    // On relance le statut jusqu'à ce que la réindexation ait abouti ; le dernier
    // passage lève l'indicateur, que la font soit apparue ou non (au-delà, c'est
    // un vrai problème et non plus un simple délai).
    pendingDelays.forEach((delay, i) => {
      setTimeout(async () => {
        await fetchDeviceStatuses();
        const done =
          i === pendingDelays.length - 1 ||
          deviceStatuses.value.find((s) => s.deviceId === deviceId)?.installed;
        if (done) markReindexing(deviceId, false);
      }, delay);
    });
  } catch (e) {
    console.error("Install error:", e);
    markReindexing(deviceId, false);
  } finally {
    const next = new Set(actionInProgress.value);
    next.delete(deviceId);
    actionInProgress.value = next;
  }
}

// Contrairement à Installer, la désactivation ne dépend pas de l'appareil en
// ligne tout de suite : c'est un état désiré, posé côté serveur, que
// l'appareil applique au prochain sync (`WatchPaths`, signal SSE ou
// `StartInterval`) — bloquer le geste jusque-là n'apporterait rien.
//
// Une famille entière (`fontIds.length > 1`) bascule d'un coup : un appel par
// style, sur l'appareil choisi. `409` (style non installé là) n'est pas une
// erreur — rien à activer/désactiver pour lui, les autres styles suffisent.
async function handleToggleActive(deviceId: string, next: boolean) {
  actionInProgress.value = new Set([...actionInProgress.value, deviceId]);
  try {
    const action = next ? "activate" : "deactivate";
    const responses = await Promise.all(
      props.fontIds.map((id) =>
        apiFetch(`/api/fonts/${id}/${action}/${deviceId}`, { method: "POST" }),
      ),
    );
    const failed = responses.find((res) => !res.ok && res.status !== 409);
    if (failed) throw new Error(`HTTP ${failed.status}`);
    await fetchDeviceStatuses();
  } catch (e) {
    console.error("Toggle active error:", e);
  } finally {
    const nextSet = new Set(actionInProgress.value);
    nextSet.delete(deviceId);
    actionInProgress.value = nextSet;
  }
}
</script>

<template>
  <Sheet>
    <SheetTrigger as-child>
      <Button
        v-if="triggerVariant === 'icon'"
        variant="ghost"
        size="icon-sm"
        @click.prevent.stop="fetchDeviceStatuses"
      >
        <Monitor class="h-3.5 w-3.5" />
      </Button>
      <Button
        v-else
        :variant="triggerVariant ?? 'outline'"
        @click="fetchDeviceStatuses"
      >
        <Monitor class="mr-2 h-4 w-4" />
        {{ triggerLabel ?? t("deviceInstall.devices") }}
      </Button>
    </SheetTrigger>
    <SheetContent>
      <SheetHeader>
        <SheetTitle>{{ t("deviceInstall.title") }}</SheetTitle>
        <SheetDescription>
          {{
            isMultiFont
              ? t("deviceInstall.descMulti", { n: fontIds.length })
              : t("deviceInstall.descSingle")
          }}
        </SheetDescription>
      </SheetHeader>

      <div class="mt-6 space-y-4">
        <!-- Note : sémantique miroir (stop-gap B1) -->
        <p class="rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">
          {{ t("deviceInstall.mirrorNote") }}
        </p>

        <!-- Loading -->
        <div v-if="devicesLoading" class="space-y-4">
          <Skeleton v-for="i in 2" :key="i" class="h-20 w-full rounded-lg" />
        </div>

        <!-- Empty -->
        <p
          v-else-if="deviceStatuses.length === 0"
          class="text-sm text-muted-foreground text-center py-8"
        >
          {{ t("deviceInstall.none") }}
        </p>

        <!-- Device list -->
        <template v-else>
          <div
            v-for="status in deviceStatuses"
            :key="status.deviceId"
            class="rounded-lg border p-4 space-y-3"
          >
            <!-- Device header -->
            <div class="flex items-center gap-2">
              <span
                class="h-2 w-2 shrink-0 rounded-full"
                :class="
                  status.isOnline ? 'bg-green-500' : 'bg-muted-foreground/40'
                "
              />
              <span class="text-sm font-medium truncate">{{
                status.deviceName
              }}</span>
              <span
                v-if="!status.isOnline"
                class="text-xs text-muted-foreground ml-auto"
                >{{ t("common.offline") }}</span
              >
            </div>

            <!-- Install status / action -->
            <div class="flex items-center justify-between gap-3">
              <div class="space-y-0.5">
                <p class="text-sm">
                  {{
                    status.installed
                      ? status.active
                        ? t("deviceInstall.present")
                        : status.mixed
                          ? t("deviceInstall.disabledPartially")
                          : t("deviceInstall.disabledHere")
                      : reindexing.has(status.deviceId)
                        ? t("deviceInstall.indexing")
                        : isMultiFont
                          ? t("deviceInstall.notInstalledMulti")
                          : t("deviceInstall.notInstalledSingle")
                  }}
                </p>
                <p
                  v-if="status.installed && status.installedAt"
                  class="text-xs text-muted-foreground"
                >
                  {{
                    t("deviceInstall.installedOn", {
                      date: formatDate(status.installedAt),
                    })
                  }}
                </p>
                <!-- macOS 14+ n'indexe pas immédiatement : le dire, sinon l'attente
                     normale passe pour un échec. -->
                <p
                  v-else-if="reindexing.has(status.deviceId)"
                  class="text-xs text-muted-foreground"
                >
                  {{ t("deviceInstall.indexingHint") }}
                </p>
              </div>
              <div class="flex items-center gap-2">
                <Loader2
                  v-if="
                    actionInProgress.has(status.deviceId) ||
                    reindexing.has(status.deviceId)
                  "
                  class="h-4 w-4 animate-spin text-muted-foreground"
                />
                <template v-if="status.installed">
                  <Badge :variant="status.active ? 'secondary' : 'outline'">{{
                    status.active
                      ? t("common.installed")
                      : status.mixed
                        ? t("deviceInstall.disabledPartially")
                        : t("deviceInstall.disabledHere")
                  }}</Badge>
                  <Switch
                    :model-value="status.active"
                    :disabled="actionInProgress.has(status.deviceId)"
                    :aria-label="t('deviceInstall.toggleActive')"
                    @update:model-value="
                      handleToggleActive(status.deviceId, $event)
                    "
                  />
                </template>
                <Button
                  v-else
                  size="sm"
                  variant="outline"
                  :disabled="
                    !status.isOnline ||
                    actionInProgress.has(status.deviceId) ||
                    reindexing.has(status.deviceId)
                  "
                  @click="handleInstall(status.deviceId)"
                >
                  {{ t("common.install") }}
                </Button>
              </div>
            </div>
          </div>
        </template>
      </div>
    </SheetContent>
  </Sheet>
</template>
