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
import { useI18n } from "vue-i18n";
import { useDevicesStore } from "@/stores/devices";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";

const { t } = useI18n();

const devicesStore = useDevicesStore();
const saving = ref<Set<string>>(new Set());

onMounted(() => {
  devicesStore.fetchDevices();
});

async function handleRescan(deviceId: string) {
  try {
    const res = await apiFetch(`/api/devices/${deviceId}/rescan`, {
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
  if (!dateStr) return t("devices.never");
  const diff = Date.now() - new Date(dateStr).getTime();
  if (diff < 0 || diff < 60_000) return t("devices.justNow");
  if (diff < 3_600_000)
    return t("devices.minutesAgo", { n: Math.floor(diff / 60_000) });
  if (diff < 86_400_000)
    return t("devices.hoursAgo", { n: Math.floor(diff / 3_600_000) });
  return t("devices.daysAgo", { n: Math.floor(diff / 86_400_000) });
}
</script>

<template>
  <div class="rounded-xl border bg-card p-6 space-y-4">
    <div class="flex items-center gap-2">
      <Monitor class="h-5 w-5 text-muted-foreground" />
      <h2 class="text-lg font-semibold">{{ t("devices.title") }}</h2>
    </div>

    <p class="text-sm text-muted-foreground">
      {{ t("devices.desc") }}
    </p>

    <!-- Loading -->
    <div v-if="devicesStore.loading" class="space-y-3">
      <Skeleton v-for="i in 2" :key="i" class="h-24 w-full rounded-xl" />
    </div>

    <!-- Empty -->
    <div
      v-else-if="devicesStore.devices.length === 0"
      class="rounded-xl border border-dashed p-8 text-center"
    >
      <p class="text-muted-foreground">{{ t("devices.none") }}</p>
      <p class="text-sm text-muted-foreground mt-1">
        {{ t("devices.installHint") }}
      </p>
    </div>

    <!-- Device list -->
    <div v-else class="space-y-4">
      <div
        v-for="device in devicesStore.devices"
        :key="device.id"
        class="rounded-xl border bg-background p-5 space-y-4"
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
              <p class="text-xs mt-0.5">
                <span
                  v-if="devicesStore.isOnline(device.id)"
                  class="text-green-600"
                >
                  {{ t("devices.connected") }}
                </span>
                <span v-else class="text-muted-foreground">
                  {{
                    t("devices.seenAgo", {
                      time: formatRelativeTime(device.lastSeenAt),
                    })
                  }}
                </span>
              </p>
            </div>
          </div>

          <div class="flex items-center gap-3 shrink-0">
            <Loader2
              v-if="saving.has(device.id)"
              class="h-4 w-4 animate-spin text-muted-foreground"
            />
            <Button
              v-if="
                device.syncStatus === 'scanning' ||
                device.syncStatus === 'syncing'
              "
              variant="outline"
              size="sm"
              disabled
            >
              <Loader2 class="mr-2 h-4 w-4 animate-spin" />
              {{
                device.syncStatus === "scanning"
                  ? t("devices.scanning")
                  : t("devices.syncing")
              }}
            </Button>
            <Button
              v-else
              variant="outline"
              size="sm"
              :disabled="!devicesStore.isOnline(device.id)"
              @click="handleRescan(device.id)"
            >
              <RefreshCw class="mr-2 h-4 w-4" />
              {{ t("devices.rescan") }}
            </Button>
          </div>
        </div>

        <Separator />

        <!-- Sync toggles -->
        <div class="grid gap-3 sm:grid-cols-2">
          <div
            class="flex items-center justify-between gap-3 rounded-lg bg-muted/50 p-3"
          >
            <div class="flex items-center gap-2.5">
              <ArrowUpFromLine class="h-4 w-4 text-muted-foreground shrink-0" />
              <Label class="text-sm font-normal cursor-pointer">
                <span class="font-medium">{{ t("devices.autoPush") }}</span>
                <span class="block text-xs text-muted-foreground">
                  {{ t("devices.autoPushDesc") }}
                </span>
              </Label>
            </div>
            <Switch
              :model-value="device.autoPush"
              :disabled="saving.has(device.id)"
              @update:model-value="toggleAutoPush(device.id, $event)"
            />
          </div>

          <div
            class="flex items-center justify-between gap-3 rounded-lg bg-muted/50 p-3"
          >
            <div class="flex items-center gap-2.5">
              <ArrowDownToLine class="h-4 w-4 text-muted-foreground shrink-0" />
              <Label class="text-sm font-normal cursor-pointer">
                <span class="font-medium">{{ t("devices.autoPull") }}</span>
                <span class="block text-xs text-muted-foreground">
                  {{ t("devices.autoPullDesc") }}
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
            <span class="text-sm font-medium">{{
              t("devices.watchedFolders")
            }}</span>
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
