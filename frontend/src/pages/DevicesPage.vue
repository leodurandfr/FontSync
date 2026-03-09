<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  Monitor,
  RefreshCw,
  Loader2,
  ArrowUpFromLine,
  ArrowDownToLine,
  FolderOpen,
} from "lucide-vue-next";
import { useDevicesStore } from "@/stores/devices";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";

const devicesStore = useDevicesStore();
const saving = ref<Set<string>>(new Set());

onMounted(() => {
  devicesStore.fetchDevices();
});

async function handleRescan(deviceId: string) {
  try {
    const res = await fetch(`/api/devices/${deviceId}/rescan`, {
      method: "POST",
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      console.error("Rescan failed:", data?.detail ?? res.status);
    }
  } catch (e) {
    console.error("Rescan error:", e);
  }
}

async function toggleAutoPush(deviceId: string, value: boolean) {
  saving.value = new Set([...saving.value, deviceId]);
  try {
    await devicesStore.updateDevice(deviceId, { autoPush: value });
  } catch (e) {
    console.error("Failed to update auto_push:", e);
  } finally {
    const next = new Set(saving.value);
    next.delete(deviceId);
    saving.value = next;
  }
}

async function toggleAutoPull(deviceId: string, value: boolean) {
  saving.value = new Set([...saving.value, deviceId]);
  try {
    await devicesStore.updateDevice(deviceId, { autoPull: value });
  } catch (e) {
    console.error("Failed to update auto_pull:", e);
  } finally {
    const next = new Set(saving.value);
    next.delete(deviceId);
    saving.value = next;
  }
}

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return "Jamais";
  const diff = Date.now() - new Date(dateStr).getTime();
  if (diff < 0 || diff < 60_000) return "À l'instant";
  if (diff < 3_600_000) return `Il y a ${Math.floor(diff / 60_000)} min`;
  if (diff < 86_400_000) return `Il y a ${Math.floor(diff / 3_600_000)} h`;
  return `Il y a ${Math.floor(diff / 86_400_000)} j`;
}
</script>

<template>
  <div>
    <h1 class="text-3xl font-bold tracking-tight">Appareils</h1>
    <p class="text-muted-foreground mt-1">
      Machines connectées à votre bibliothèque FontSync.
    </p>

    <!-- Loading -->
    <div v-if="devicesStore.loading" class="mt-8 space-y-3">
      <Skeleton v-for="i in 3" :key="i" class="h-24 w-full rounded-xl" />
    </div>

    <!-- Empty -->
    <div
      v-else-if="devicesStore.devices.length === 0"
      class="mt-8 rounded-xl border border-dashed p-12 text-center"
    >
      <p class="text-muted-foreground">Aucun appareil enregistré.</p>
      <p class="text-sm text-muted-foreground mt-1">
        Installez l'agent FontSync sur une machine pour commencer.
      </p>
    </div>

    <!-- Device list -->
    <div v-else class="mt-8 space-y-4">
      <div
        v-for="device in devicesStore.devices"
        :key="device.id"
        class="rounded-xl border bg-card p-5 space-y-4"
      >
        <!-- Header: info + actions -->
        <div class="flex items-center justify-between gap-4">
          <div class="flex items-center gap-4 min-w-0">
            <Monitor class="h-8 w-8 shrink-0 text-muted-foreground" />
            <div class="min-w-0">
              <div class="flex items-center gap-2">
                <span
                  class="h-2 w-2 shrink-0 rounded-full"
                  :class="
                    devicesStore.isOnline(device.id)
                      ? 'bg-green-500'
                      : 'bg-muted-foreground/40'
                  "
                />
                <p class="font-semibold truncate">{{ device.name }}</p>
              </div>
              <p class="text-sm text-muted-foreground truncate">
                {{ device.hostname }} &middot; {{ device.os }}
                <span v-if="device.osVersion"> {{ device.osVersion }}</span>
                <span v-if="device.agentVersion">
                  &middot; Agent v{{ device.agentVersion }}
                </span>
              </p>
              <p class="text-xs text-muted-foreground mt-0.5">
                Vu {{ formatRelativeTime(device.lastSeenAt) }}
              </p>
            </div>
          </div>

          <div class="flex items-center gap-3 shrink-0">
            <Loader2
              v-if="saving.has(device.id)"
              class="h-4 w-4 animate-spin text-muted-foreground"
            />
            <Button
              v-if="device.syncStatus === 'scanning' || device.syncStatus === 'syncing'"
              variant="outline"
              size="sm"
              disabled
            >
              <Loader2 class="mr-2 h-4 w-4 animate-spin" />
              {{ device.syncStatus === 'scanning' ? 'Scan en cours…' : 'Synchronisation…' }}
            </Button>
            <Button
              v-else
              variant="outline"
              size="sm"
              :disabled="!devicesStore.isOnline(device.id)"
              @click="handleRescan(device.id)"
            >
              <RefreshCw class="mr-2 h-4 w-4" />
              Re-scan
            </Button>
          </div>
        </div>

        <Separator />

        <!-- Sync toggles -->
        <div class="grid gap-3 sm:grid-cols-2">
          <div class="flex items-center justify-between gap-3 rounded-lg bg-muted/50 p-3">
            <div class="flex items-center gap-2.5">
              <ArrowUpFromLine class="h-4 w-4 text-muted-foreground shrink-0" />
              <Label class="text-sm font-normal cursor-pointer">
                <span class="font-medium">Push automatique</span>
                <span class="block text-xs text-muted-foreground">
                  Envoie les nouvelles polices au serveur
                </span>
              </Label>
            </div>
            <Switch
              :model-value="device.autoPush"
              :disabled="saving.has(device.id)"
              @update:model-value="toggleAutoPush(device.id, $event)"
            />
          </div>

          <div class="flex items-center justify-between gap-3 rounded-lg bg-muted/50 p-3">
            <div class="flex items-center gap-2.5">
              <ArrowDownToLine class="h-4 w-4 text-muted-foreground shrink-0" />
              <Label class="text-sm font-normal cursor-pointer">
                <span class="font-medium">Pull automatique</span>
                <span class="block text-xs text-muted-foreground">
                  Installe les polices du serveur sur cet appareil
                </span>
              </Label>
            </div>
            <Switch
              :model-value="device.autoPull"
              :disabled="saving.has(device.id)"
              @update:model-value="toggleAutoPull(device.id, $event)"
            />
          </div>
        </div>

        <!-- Font directories -->
        <div v-if="device.fontDirectories?.length">
          <div class="flex items-center gap-2 mb-2">
            <FolderOpen class="h-4 w-4 text-muted-foreground" />
            <span class="text-sm font-medium">Dossiers surveillés</span>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <code
              v-for="dir in device.fontDirectories"
              :key="dir"
              class="rounded border bg-muted/50 px-2 py-0.5 text-xs font-mono"
            >
              {{ dir }}
            </code>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
