<script setup lang="ts">
import { onMounted } from 'vue'
import { useDevicesStore } from '@/stores/devices'
import { Badge } from '@/components/ui/badge'

const devicesStore = useDevicesStore()

onMounted(() => {
  devicesStore.fetchDevices()
})
</script>

<template>
  <div>
    <h1 class="text-3xl font-bold tracking-tight">Appareils</h1>
    <p class="text-muted-foreground mt-1">
      Machines connectées à votre bibliothèque FontSync.
    </p>

    <div class="mt-8 space-y-3">
      <div
        v-if="devicesStore.devices.length === 0"
        class="rounded-xl border border-dashed p-12 text-center"
      >
        <p class="text-muted-foreground">
          Aucun appareil enregistré.
        </p>
      </div>
      <div
        v-for="device in devicesStore.devices"
        :key="device.id"
        class="flex items-center justify-between rounded-xl border bg-card p-5"
      >
        <div>
          <p class="font-semibold">{{ device.name }}</p>
          <p class="text-sm text-muted-foreground">
            {{ device.hostname }} &middot; {{ device.os }}
          </p>
        </div>
        <Badge :variant="devicesStore.isOnline(device.id) ? 'default' : 'secondary'">
          {{ devicesStore.isOnline(device.id) ? 'En ligne' : 'Hors ligne' }}
        </Badge>
      </div>
    </div>
  </div>
</template>
