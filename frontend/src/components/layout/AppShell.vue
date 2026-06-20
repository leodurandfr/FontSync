<script setup lang="ts">
import { onMounted, onUnmounted, watch } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "vue-i18n";
import { PanelLeftOpen } from "lucide-vue-next";
import AppSidebar from "./AppSidebar.vue";
import { Panel } from "@/components/ui/panel";
import { useWebSocket } from "@/composables/useWebSocket";
import { useLayoutStore } from "@/stores/layout";

const { t } = useI18n();
const layout = useLayoutStore();
const route = useRoute();

// Sur mobile, la sidebar est un drawer en surimpression : on la replie au
// montage et à chaque navigation pour ne pas couvrir le contenu. Fermeture
// transitoire (persist=false) pour préserver la préférence desktop.
const mobileMql = window.matchMedia("(max-width: 639px)");
onMounted(() => {
  if (mobileMql.matches) layout.setSidebarOpen(false, false);
});
watch(
  () => route.fullPath,
  () => {
    if (mobileMql.matches) layout.setSidebarOpen(false, false);
  },
);

// L'écran de saisie du token (App.vue) démonte cette coquille sur un 401 /
// WS 1008 : on ferme alors proprement la connexion WebSocket pour ne pas la
// voir tenter de se reconnecter avec un token refusé.
const { disconnect } = useWebSocket();
onUnmounted(disconnect);
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-background">
    <!-- Backdrop du drawer mobile -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      leave-active-class="transition-opacity duration-200"
      leave-to-class="opacity-0"
    >
      <div
        v-if="layout.sidebarOpen"
        class="fixed inset-0 z-40 bg-black/50 sm:hidden"
        aria-hidden="true"
        @click="layout.setSidebarOpen(false, false)"
      />
    </Transition>

    <AppSidebar />

    <!-- Bouton de réouverture (la page Fonts l'intègre dans sa toolbar) -->
    <Panel
      v-if="!layout.sidebarOpen && route.name !== 'fonts'"
      as="button"
      class="absolute left-3 top-3 z-40 flex size-9 items-center justify-center text-foreground-subtle transition-colors hover:text-muted-foreground"
      :aria-label="t('sidebar.openSidebar')"
      @click="layout.setSidebarOpen(true)"
    >
      <PanelLeftOpen class="size-4" :stroke-width="1.5" />
    </Panel>

    <main class="relative min-w-0 flex-1 overflow-hidden">
      <!--
        Crossfade entre pages : opacity seule (composité GPU, aucun reflow) et
        mode out-in pour un vrai fade-out → fade-in séquentiel. La clé sur la
        route racine évite de ré-animer un simple changement de query/param.
      -->
      <RouterView v-slot="{ Component }">
        <Transition name="page" mode="out-in">
          <component :is="Component" :key="route.name" />
        </Transition>
      </RouterView>
    </main>
  </div>
</template>
