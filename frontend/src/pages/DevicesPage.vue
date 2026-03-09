<script setup lang="ts">
import { onMounted } from "vue";
import { Monitor, RefreshCw, Loader2 } from "lucide-vue-next";
import { useDevicesStore } from "@/stores/devices";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

const devicesStore = useDevicesStore();

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
    <div v-else class="mt-8 space-y-3">
      <div
        v-for="device in devicesStore.devices"
        :key="device.id"
        class="flex items-center justify-between gap-4 rounded-xl border bg-card p-5"
      >
        <!-- Left: info -->
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
              <span v-if="device.osVersion">{{ device.osVersion }}</span>
            </p>
            <p class="text-xs text-muted-foreground mt-0.5">
              Vu {{ formatRelativeTime(device.lastSeenAt) }}
            </p>
          </div>
        </div>

        <!-- Right: status + actions -->
        <div class="flex items-center gap-3 shrink-0">
          <Button
            v-if="device.syncStatus === 'scanning' || device.syncStatus === 'syncing'"
            variant="outline"
            size="sm"
            disabled
          >
            <Loader2 class="mr-2 h-4 w-4 animate-spin" />
            {{ device.syncStatus === 'scanning' ? 'Scan en cours…' : 'Synchronisation…' }}
          </Button>
          <template v-else>
            <Button
              variant="outline"
              size="sm"
              :disabled="!devicesStore.isOnline(device.id)"
              @click="handleRescan(device.id)"
            >
              <RefreshCw class="mr-2 h-4 w-4" />
              Re-scan
            </Button>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>
