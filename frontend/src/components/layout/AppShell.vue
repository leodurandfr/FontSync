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
import { useSidebarMode } from "@/composables/useSidebarMode";
import { useLayoutStore } from "@/stores/layout";

const { t } = useI18n();
const layout = useLayoutStore();
const route = useRoute();
const { isOverlay } = useSidebarMode();

// L'écran de saisie du token (App.vue) démonte cette coquille sur un 401 /
// WS 1008 : on ferme alors proprement la connexion WebSocket pour ne pas la
// voir tenter de se reconnecter avec un token refusé.
const { disconnect } = useWebSocket();
onUnmounted(disconnect);
</script>

<template>
  <!--
    Au-dessus de 740px : modèle Finder, la sidebar pousse le contenu et élargit
    la fenêtre native si besoin (layout store → ensureWindowWidth). En dessous :
    elle passe en drawer overlay au-dessus du contenu, avec le backdrop ci-après
    (cf. useSidebarMode + AppSidebar).
  -->
  <div class="flex h-screen overflow-hidden bg-background">
    <!-- Backdrop du drawer overlay (fenêtre étroite < 740px) -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      leave-active-class="transition-opacity duration-200"
      leave-to-class="opacity-0"
    >
      <div
        v-if="layout.sidebarOpen && isOverlay"
        class="fixed inset-0 z-40 bg-black/50"
        aria-hidden="true"
        @click="layout.setSidebarOpen(false)"
      />
    </Transition>

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

    <!--
      En mode « push » sidebar ouverte, on tire le contenu de 12px vers la
      gauche (la demi-gouttière à droite du panneau) pour que sa bordure vienne
      affleurer le bord du panneau : les filets séparateurs des fontes semblent
      ainsi filer sous la sidebar. Désactivé fermé / en overlay, sinon le
      `overflow-hidden` parent rognerait 12px de contenu à gauche.
    -->
    <main
      class="relative min-w-0 flex-1 overflow-hidden"
      :class="!isOverlay && layout.sidebarOpen ? '-ml-3' : ''"
    >
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
