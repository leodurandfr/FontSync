<script setup lang="ts">
import { ref, computed } from "vue";
import { Monitor, Loader2 } from "lucide-vue-next";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
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

const isMultiFont = computed(() => props.fontIds.length > 1);

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
    const res = await apiFetch(`/api/fonts/${props.fontIds[0]}/devices`);
    if (res.ok) {
      deviceStatuses.value = await res.json();
    }
  } catch (e) {
    console.error("Failed to fetch device statuses:", e);
  } finally {
    devicesLoading.value = false;
  }
}

// Stop-gap B1 : le modèle de sync est un *miroir* (l'appareil pulle les fonts du
// serveur selon `auto_pull`). « Installer » ne pousse donc pas une commande
// ciblée : il déclenche un re-sync de l'appareil. La désinstallation et
// l'activation par appareil (sélectives) sont reportées au redesign « manifeste
// désiré » — d'où l'absence de ces toggles ici.
async function handleInstall(deviceId: string) {
  actionInProgress.value = new Set([...actionInProgress.value, deviceId]);
  try {
    // Un seul appel suffit : le re-sync récupère toutes les fonts manquantes.
    await apiFetch(`/api/fonts/${props.fontIds[0]}/install/${deviceId}`, {
      method: "POST",
    });
    // L'installation réelle suit le re-sync de l'agent → on rafraîchit le statut.
    setTimeout(() => fetchDeviceStatuses(), 2000);
  } catch (e) {
    console.error("Install error:", e);
  } finally {
    const next = new Set(actionInProgress.value);
    next.delete(deviceId);
    actionInProgress.value = next;
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
              ? `Synchronisez ces ${fontIds.length} polices sur vos machines connectées.`
              : "Synchronisez cette police sur vos machines connectées."
          }}
        </SheetDescription>
      </SheetHeader>

      <div class="mt-6 space-y-4">
        <!-- Note : sémantique miroir (stop-gap B1) -->
        <p class="rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">
          Les polices se synchronisent en miroir selon le réglage « pull
          automatique » de chaque appareil. La désinstallation et l'activation
          par appareil arrivent dans une prochaine version.
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
          Aucun appareil enregistré.
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
                >Hors ligne</span
              >
            </div>

            <!-- Install status / action -->
            <div class="flex items-center justify-between gap-3">
              <div class="space-y-0.5">
                <p class="text-sm">
                  {{
                    status.installed
                      ? "Présente sur l'appareil"
                      : isMultiFont
                        ? "Non installées"
                        : "Non installée"
                  }}
                </p>
                <p
                  v-if="status.installed && status.installedAt"
                  class="text-xs text-muted-foreground"
                >
                  Installée le {{ formatDate(status.installedAt) }}
                </p>
              </div>
              <div class="flex items-center gap-2">
                <Loader2
                  v-if="actionInProgress.has(status.deviceId)"
                  class="h-4 w-4 animate-spin text-muted-foreground"
                />
                <Badge v-if="status.installed" variant="secondary"
                  >Installée</Badge
                >
                <Button
                  v-else
                  size="sm"
                  variant="outline"
                  :disabled="
                    !status.isOnline || actionInProgress.has(status.deviceId)
                  "
                  @click="handleInstall(status.deviceId)"
                >
                  Installer
                </Button>
              </div>
            </div>
          </div>
        </template>
      </div>
    </SheetContent>
  </Sheet>
</template>
