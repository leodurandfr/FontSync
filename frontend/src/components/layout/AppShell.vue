<script setup lang="ts">
import { onUnmounted } from "vue";
import { PanelLeftOpen } from "lucide-vue-next";
import AppSidebar from "./AppSidebar.vue";
import { Panel } from "@/components/ui/panel";
import { useWebSocket } from "@/composables/useWebSocket";
import { useLayoutStore } from "@/stores/layout";

const layout = useLayoutStore();

// L'écran de saisie du token (App.vue) démonte cette coquille sur un 401 /
// WS 1008 : on ferme alors proprement la connexion WebSocket pour ne pas la
// voir tenter de se reconnecter avec un token refusé.
const { disconnect } = useWebSocket();
onUnmounted(disconnect);
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-background">
    <AppSidebar />

    <!-- Bouton de réouverture (visible toutes routes quand replié) -->
    <Panel
      v-if="!layout.sidebarOpen"
      as="button"
      class="absolute left-3 top-3 z-40 flex size-9 items-center justify-center text-foreground-subtle transition-colors hover:text-muted-foreground"
      aria-label="Ouvrir la sidebar"
      @click="layout.setSidebarOpen(true)"
    >
      <PanelLeftOpen class="size-4" :stroke-width="1.5" />
    </Panel>

    <main class="relative min-w-0 flex-1 overflow-hidden">
      <RouterView />
    </main>
  </div>
</template>
