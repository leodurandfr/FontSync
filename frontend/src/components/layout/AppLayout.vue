<script setup lang="ts">
import { onUnmounted } from 'vue'
import AppHeader from './AppHeader.vue'
import { useWebSocket } from '@/composables/useWebSocket'

// L'écran de saisie du token (App.vue) démonte ce layout sur un 401 / WS 1008 :
// on ferme alors proprement la connexion WebSocket pour ne pas la voir tenter
// de se reconnecter avec un token refusé.
const { disconnect } = useWebSocket()
onUnmounted(disconnect)
</script>

<template>
  <div class="flex h-screen flex-col">
    <AppHeader />
    <main class="flex-1 overflow-auto">
      <RouterView />
    </main>
  </div>
</template>
