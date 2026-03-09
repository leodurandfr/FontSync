<script setup lang="ts">
import AppHeader from './AppHeader.vue'
import { useWebSocket } from '@/composables/useWebSocket'

useWebSocket()
</script>

<template>
  <div class="flex h-screen flex-col">
    <AppHeader />
    <main class="flex-1 overflow-auto">
      <RouterView />
    </main>
  </div>
</template>
