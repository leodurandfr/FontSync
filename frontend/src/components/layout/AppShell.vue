<script setup lang="ts">
import { onUnmounted } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "vue-i18n";
import { PanelLeftOpen } from "lucide-vue-next";
import AppSidebar from "./AppSidebar.vue";
import WindowControls from "./WindowControls.vue";
import { Panel } from "@/components/ui/panel";
import { useWebSocket } from "@/composables/useWebSocket";
import { showWindowControls } from "@/composables/useWindowControls";
import { useLayoutStore } from "@/stores/layout";

const { t } = useI18n();
const layout = useLayoutStore();
const route = useRoute();

// L'écran de saisie du token (App.vue) démonte cette coquille sur un 401 /
// WS 1008 : on ferme alors proprement la connexion WebSocket pour ne pas la
// voir tenter de se reconnecter avec un token refusé.
const { disconnect } = useWebSocket();
onUnmounted(disconnect);
</script>

<template>
  <!--
    Modèle Finder : la sidebar pousse le contenu (jamais d'overlay, pas de
    basculement par largeur). Si la fenêtre native est trop étroite à
    l'ouverture, elle s'agrandit (cf. layout store → ensureWindowWidth).
  -->
  <div class="flex h-screen overflow-hidden bg-background">
    <AppSidebar />

    <!-- Feux de fenêtre + réouverture (la page Fonts l'intègre dans sa toolbar) -->
    <Panel
      v-if="!layout.sidebarOpen && route.name !== 'fonts'"
      class="absolute left-3 top-3 z-40 flex h-9 items-center gap-3 pl-5 pr-3"
      data-window-drag
    >
      <WindowControls v-if="showWindowControls" />
      <span
        v-if="showWindowControls"
        class="h-4 w-px flex-shrink-0 bg-separator"
        aria-hidden="true"
      />
      <button
        type="button"
        class="flex items-center text-foreground-subtle transition-colors hover:text-muted-foreground"
        :aria-label="t('sidebar.openSidebar')"
        @click="layout.setSidebarOpen(true)"
      >
        <PanelLeftOpen class="size-4" :stroke-width="1.5" />
      </button>
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
