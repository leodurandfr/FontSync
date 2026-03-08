<script setup lang="ts">
import { useFontsStore } from '@/stores/fonts'
import { useDevicesStore } from '@/stores/devices'

const fontsStore = useFontsStore()
const devicesStore = useDevicesStore()
</script>

<template>
  <div>
    <h1 class="text-3xl font-bold tracking-tight">Dashboard</h1>
    <p class="text-muted-foreground mt-1">
      Vue d'ensemble de votre bibliothèque de polices.
    </p>

    <div class="mt-8 grid gap-4 md:grid-cols-3">
      <div class="rounded-xl border bg-card p-6">
        <p class="text-sm font-medium text-muted-foreground">Polices</p>
        <p class="text-3xl font-bold tracking-tight mt-1">
          {{ fontsStore.total }}
        </p>
      </div>
      <div class="rounded-xl border bg-card p-6">
        <p class="text-sm font-medium text-muted-foreground">Appareils</p>
        <p class="text-3xl font-bold tracking-tight mt-1">
          {{ devicesStore.devices.length }}
        </p>
      </div>
      <div class="rounded-xl border bg-card p-6">
        <p class="text-sm font-medium text-muted-foreground">Connectés</p>
        <p class="text-3xl font-bold tracking-tight mt-1">
          {{ devicesStore.onlineCount }}
        </p>
      </div>
    </div>
  </div>
</template>
