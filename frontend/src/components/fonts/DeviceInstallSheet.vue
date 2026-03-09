<script setup lang="ts">
import { ref, computed } from "vue";
import { Monitor, Loader2 } from "lucide-vue-next";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

interface DeviceStatus {
  deviceId: string;
  deviceName: string;
  hostname: string;
  isOnline: boolean;
  installed: boolean;
  activated: boolean;
  localPath: string | null;
  installedAt: string | null;
}

const props = defineProps<{
  fontIds: string[];
  triggerVariant?: "outline" | "ghost" | "icon";
  triggerLabel?: string;
}>();

const deviceStatuses = ref<DeviceStatus[]>([]);
const devicesLoading = ref(false);
const actionInProgress = ref<Set<string>>(new Set());
const activationInProgress = ref<Set<string>>(new Set());

const isMultiFont = computed(() => props.fontIds.length > 1);

function isSystemFont(localPath: string | null): boolean {
  if (!localPath) return false;
  return (
    localPath.startsWith("/Library/Fonts") ||
    localPath.startsWith("/System/Library/Fonts")
  );
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("fr-FR", {
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
    // For multi-font, fetch statuses for the first font (all devices are the same)
    const res = await fetch(`/api/fonts/${props.fontIds[0]}/devices`);
    if (res.ok) {
      deviceStatuses.value = await res.json();
    }
  } catch (e) {
    console.error("Failed to fetch device statuses:", e);
  } finally {
    devicesLoading.value = false;
  }
}

async function handleInstall(deviceId: string) {
  actionInProgress.value = new Set([...actionInProgress.value, deviceId]);
  try {
    const results = await Promise.allSettled(
      props.fontIds.map((fontId) =>
        fetch(`/api/fonts/${fontId}/install/${deviceId}`, { method: "POST" }),
      ),
    );
    const allOk = results.every(
      (r) => r.status === "fulfilled" && r.value.ok,
    );
    if (allOk) {
      const status = deviceStatuses.value.find(
        (s) => s.deviceId === deviceId,
      );
      if (status) {
        status.installed = true;
        status.activated = true;
      }
    }
    setTimeout(() => fetchDeviceStatuses(), 2000);
  } catch (e) {
    console.error("Install error:", e);
  } finally {
    const next = new Set(actionInProgress.value);
    next.delete(deviceId);
    actionInProgress.value = next;
  }
}

async function handleUninstall(deviceId: string) {
  actionInProgress.value = new Set([...actionInProgress.value, deviceId]);
  try {
    const results = await Promise.allSettled(
      props.fontIds.map((fontId) =>
        fetch(`/api/fonts/${fontId}/uninstall/${deviceId}`, { method: "POST" }),
      ),
    );
    const allOk = results.every(
      (r) => r.status === "fulfilled" && r.value.ok,
    );
    if (allOk) {
      const status = deviceStatuses.value.find(
        (s) => s.deviceId === deviceId,
      );
      if (status) {
        status.installed = false;
        status.activated = false;
        status.localPath = null;
        status.installedAt = null;
      }
    }
    setTimeout(() => fetchDeviceStatuses(), 2000);
  } catch (e) {
    console.error("Uninstall error:", e);
  } finally {
    const next = new Set(actionInProgress.value);
    next.delete(deviceId);
    actionInProgress.value = next;
  }
}

async function handleActivate(deviceId: string) {
  activationInProgress.value = new Set([
    ...activationInProgress.value,
    deviceId,
  ]);
  try {
    const results = await Promise.allSettled(
      props.fontIds.map((fontId) =>
        fetch(`/api/fonts/${fontId}/activate/${deviceId}`, { method: "POST" }),
      ),
    );
    const allOk = results.every(
      (r) => r.status === "fulfilled" && r.value.ok,
    );
    if (allOk) {
      setTimeout(() => fetchDeviceStatuses(), 2000);
    }
  } catch (e) {
    console.error("Activate error:", e);
  } finally {
    const next = new Set(activationInProgress.value);
    next.delete(deviceId);
    activationInProgress.value = next;
  }
}

async function handleDeactivate(deviceId: string) {
  activationInProgress.value = new Set([
    ...activationInProgress.value,
    deviceId,
  ]);
  try {
    const results = await Promise.allSettled(
      props.fontIds.map((fontId) =>
        fetch(`/api/fonts/${fontId}/deactivate/${deviceId}`, {
          method: "POST",
        }),
      ),
    );
    const allOk = results.every(
      (r) => r.status === "fulfilled" && r.value.ok,
    );
    if (allOk) {
      const status = deviceStatuses.value.find(
        (s) => s.deviceId === deviceId,
      );
      if (status) {
        status.activated = false;
      }
    }
  } catch (e) {
    console.error("Deactivate error:", e);
  } finally {
    const next = new Set(activationInProgress.value);
    next.delete(deviceId);
    activationInProgress.value = next;
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
        {{ triggerLabel ?? "Appareils" }}
      </Button>
    </SheetTrigger>
    <SheetContent>
      <SheetHeader>
        <SheetTitle>Installation par appareil</SheetTitle>
        <SheetDescription>
          {{
            isMultiFont
              ? `Gérez l'installation de ces ${fontIds.length} polices sur chaque machine connectée.`
              : "Gérez l'installation de cette police sur chaque machine connectée."
          }}
        </SheetDescription>
      </SheetHeader>

      <div class="mt-6 space-y-4">
        <!-- Loading -->
        <div v-if="devicesLoading" class="space-y-4">
          <Skeleton
            v-for="i in 2"
            :key="i"
            class="h-28 w-full rounded-lg"
          />
        </div>

        <!-- Empty -->
        <p
          v-else-if="deviceStatuses.length === 0"
          class="text-sm text-muted-foreground text-center py-8"
        >
          Aucun appareil enregistré.
        </p>

        <!-- Device list -->
        <template v-else>
          <div
            v-for="status in deviceStatuses"
            :key="status.deviceId"
            class="rounded-lg border p-4 space-y-4"
          >
            <!-- Device header -->
            <div class="flex items-center gap-2">
              <span
                class="h-2 w-2 shrink-0 rounded-full"
                :class="
                  status.isOnline
                    ? 'bg-green-500'
                    : 'bg-muted-foreground/40'
                "
              />
              <span class="text-sm font-medium truncate">{{
                status.deviceName
              }}</span>
              <span
                v-if="!status.isOnline"
                class="text-xs text-muted-foreground ml-auto"
                >Hors ligne</span
              >
            </div>

            <!-- Install toggle -->
            <div class="flex items-center justify-between gap-3">
              <div class="space-y-0.5">
                <Label class="text-sm">{{
                  isMultiFont
                    ? "Installer les polices"
                    : "Installer la police"
                }}</Label>
                <p class="text-xs text-muted-foreground">
                  {{
                    status.installed
                      ? "Fichier présent sur l'appareil"
                      : isMultiFont
                        ? "Non installées"
                        : "Non installée"
                  }}
                </p>
              </div>
              <div class="flex items-center gap-2">
                <Loader2
                  v-if="actionInProgress.has(status.deviceId)"
                  class="h-4 w-4 animate-spin text-muted-foreground"
                />
                <Switch
                  :model-value="status.installed"
                  :disabled="
                    !status.isOnline ||
                    actionInProgress.has(status.deviceId)
                  "
                  @update:model-value="
                    status.installed
                      ? handleUninstall(status.deviceId)
                      : handleInstall(status.deviceId)
                  "
                />
              </div>
            </div>

            <!-- Activate toggle -->
            <div class="flex items-center justify-between gap-3">
              <div class="space-y-0.5">
                <Label
                  class="text-sm"
                  :class="!status.installed && 'text-muted-foreground'"
                  >Activer sur le système</Label
                >
                <p class="text-xs text-muted-foreground">
                  <template v-if="!status.installed"
                    >Installez d'abord la police</template
                  >
                  <template v-else-if="isSystemFont(status.localPath)"
                    >Police système (non modifiable)</template
                  >
                  <template v-else-if="status.activated"
                    >Disponible dans les applications</template
                  >
                  <template v-else
                    >Désactivée — invisible pour les applications</template
                  >
                </p>
              </div>
              <div class="flex items-center gap-2">
                <Loader2
                  v-if="activationInProgress.has(status.deviceId)"
                  class="h-4 w-4 animate-spin text-muted-foreground"
                />
                <Switch
                  :model-value="status.activated"
                  :disabled="
                    !status.installed ||
                    !status.isOnline ||
                    isSystemFont(status.localPath) ||
                    activationInProgress.has(status.deviceId)
                  "
                  @update:model-value="
                    status.activated
                      ? handleDeactivate(status.deviceId)
                      : handleActivate(status.deviceId)
                  "
                />
              </div>
            </div>

            <p
              v-if="status.installed && status.installedAt"
              class="text-xs text-muted-foreground"
            >
              Installée le {{ formatDate(status.installedAt) }}
            </p>
          </div>
        </template>
      </div>
    </SheetContent>
  </Sheet>
</template>
