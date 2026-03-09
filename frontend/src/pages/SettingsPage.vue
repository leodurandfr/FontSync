<script setup lang="ts">
import { computed, onMounted } from 'vue'
import {
  Copy,
  Download,
  Server,
  Check,
  Monitor,
  ArrowDownToLine,
  ArrowUpFromLine,
  FolderOpen,
  Loader2,
} from 'lucide-vue-next'
import { ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Separator } from '@/components/ui/separator'
import { useWsStore } from '@/stores/ws'
import { useDevicesStore } from '@/stores/devices'
import { storeToRefs } from 'pinia'

const wsStore = useWsStore()
const { status } = storeToRefs(wsStore)
const devicesStore = useDevicesStore()

const serverUrl = computed(() => window.location.origin)
const copied = ref(false)

/** IDs des devices en cours de sauvegarde */
const saving = ref<Set<string>>(new Set())

onMounted(() => {
  devicesStore.fetchDevices()
})

async function copyUrl() {
  await navigator.clipboard.writeText(serverUrl.value)
  copied.value = true
  setTimeout(() => (copied.value = false), 2000)
}

const wsStatusLabel = computed(() => {
  switch (status.value) {
    case 'connected':
      return 'Connecté'
    case 'connecting':
      return 'Connexion...'
    default:
      return 'Déconnecté'
  }
})

const wsStatusVariant = computed<'default' | 'secondary' | 'destructive'>(() => {
  switch (status.value) {
    case 'connected':
      return 'default'
    case 'connecting':
      return 'secondary'
    default:
      return 'destructive'
  }
})

async function toggleAutoPull(deviceId: string, value: boolean) {
  saving.value = new Set([...saving.value, deviceId])
  try {
    await devicesStore.updateDevice(deviceId, { autoPull: value })
  } catch (e) {
    console.error('Failed to update auto_pull:', e)
  } finally {
    const next = new Set(saving.value)
    next.delete(deviceId)
    saving.value = next
  }
}

async function toggleAutoPush(deviceId: string, value: boolean) {
  saving.value = new Set([...saving.value, deviceId])
  try {
    await devicesStore.updateDevice(deviceId, { autoPush: value })
  } catch (e) {
    console.error('Failed to update auto_push:', e)
  } finally {
    const next = new Set(saving.value)
    next.delete(deviceId)
    saving.value = next
  }
}
</script>

<template>
  <div>
    <h1 class="text-3xl font-bold tracking-tight">Paramètres</h1>
    <p class="text-muted-foreground mt-1">
      Configuration de votre instance FontSync.
    </p>

    <div class="mt-8 space-y-6">
      <!-- Server info -->
      <div class="rounded-xl border bg-card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <Server class="h-5 w-5 text-muted-foreground" />
          <h2 class="text-lg font-semibold">Serveur</h2>
        </div>

        <div class="space-y-3">
          <div>
            <p class="text-sm text-muted-foreground mb-1">URL du serveur</p>
            <div class="flex items-center gap-2">
              <code
                class="flex-1 rounded-lg border bg-muted/50 px-3 py-2 text-sm font-mono"
              >
                {{ serverUrl }}
              </code>
              <Button variant="outline" size="icon" @click="copyUrl">
                <Check v-if="copied" class="h-4 w-4 text-green-500" />
                <Copy v-else class="h-4 w-4" />
              </Button>
            </div>
          </div>

          <div>
            <p class="text-sm text-muted-foreground mb-1">WebSocket</p>
            <Badge :variant="wsStatusVariant">{{ wsStatusLabel }}</Badge>
          </div>
        </div>
      </div>

      <!-- Devices config -->
      <div class="rounded-xl border bg-card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <Monitor class="h-5 w-5 text-muted-foreground" />
          <h2 class="text-lg font-semibold">Appareils</h2>
        </div>

        <p class="text-sm text-muted-foreground">
          Configurez la synchronisation pour chaque appareil connecté.
        </p>

        <!-- Loading -->
        <div v-if="devicesStore.loading" class="space-y-3">
          <Skeleton v-for="i in 2" :key="i" class="h-32 w-full rounded-lg" />
        </div>

        <!-- Empty -->
        <div
          v-else-if="devicesStore.devices.length === 0"
          class="rounded-lg border border-dashed p-8 text-center"
        >
          <p class="text-sm text-muted-foreground">
            Aucun appareil enregistré. Installez l'agent sur un Mac pour commencer.
          </p>
        </div>

        <!-- Device cards -->
        <div v-else class="space-y-4">
          <div
            v-for="device in devicesStore.devices"
            :key="device.id"
            class="rounded-lg border p-5 space-y-4"
          >
            <!-- Header -->
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-3">
                <span
                  class="h-2.5 w-2.5 shrink-0 rounded-full"
                  :class="
                    devicesStore.isOnline(device.id)
                      ? 'bg-green-500'
                      : 'bg-muted-foreground/40'
                  "
                />
                <div>
                  <p class="font-medium">{{ device.name }}</p>
                  <p class="text-xs text-muted-foreground">
                    {{ device.hostname }} &middot; {{ device.os }}
                    <span v-if="device.osVersion"> {{ device.osVersion }}</span>
                    <span v-if="device.agentVersion">
                      &middot; Agent v{{ device.agentVersion }}
                    </span>
                  </p>
                </div>
              </div>
              <Loader2
                v-if="saving.has(device.id)"
                class="h-4 w-4 animate-spin text-muted-foreground"
              />
            </div>

            <Separator />

            <!-- Sync toggles -->
            <div class="grid gap-4 sm:grid-cols-2">
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
                  :checked="device.autoPush"
                  :disabled="saving.has(device.id)"
                  @update:checked="toggleAutoPush(device.id, $event)"
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
                  :checked="device.autoPull"
                  :disabled="saving.has(device.id)"
                  @update:checked="toggleAutoPull(device.id, $event)"
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

      <!-- Agent download -->
      <div class="rounded-xl border bg-card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <Download class="h-5 w-5 text-muted-foreground" />
          <h2 class="text-lg font-semibold">Agent de synchronisation</h2>
        </div>

        <p class="text-sm text-muted-foreground">
          L'agent FontSync tourne en arrière-plan sur votre Mac. Il détecte
          automatiquement les nouvelles polices installées et les synchronise
          avec le serveur.
        </p>

        <Button variant="outline" disabled>
          <Download class="mr-2 h-4 w-4" />
          Télécharger FontSync.app pour macOS
        </Button>
        <p class="text-xs text-muted-foreground">
          Le téléchargement de l'agent sera disponible prochainement.
        </p>
      </div>
    </div>
  </div>
</template>
