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
    Feux de fenêtre : un seul exemplaire, réel et interactif, en position fixe
    par rapport à la fenêtre — comme les vrais traffic lights macOS, qui sont
    du chrome de fenêtre et ne bougent jamais quel que soit le contenu en
    dessous. Les trois autres emplacements historiques (header sidebar, panel
    de réouverture, bloc toolbar de la page fonts) ne réservent plus qu'un
    espace invisible de même taille, pour que boutons/labels voisins gardent
    leur position sans dédoubler ni faire glisser les feux pendant les
    transitions. `z-[60]` : au-dessus de la sidebar en mode overlay (z-50).
  -->
  <WindowControls
    v-if="showWindowControls"
    class="fixed left-[28px] top-[26px] z-[60]"
  />

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

    <!-- Espace réservé + réouverture (la page Fonts l'intègre dans sa toolbar) -->
    <Panel
      v-if="!layout.sidebarOpen && route.name !== 'fonts'"
      class="absolute left-2 top-2 z-40 flex h-12 items-center gap-3 pl-5 pr-3"
      data-window-drag
    >
      <!-- Espaceur invisible : le vrai exemplaire, fixe, est plus haut dans ce fichier. -->
      <WindowControls v-if="showWindowControls" class="invisible" />
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
      En mode « push » sidebar ouverte, on tire le contenu de 8px vers la
      gauche (la demi-gouttière à droite du panneau) pour que sa bordure vienne
      affleurer le bord du panneau : les filets séparateurs des fontes semblent
      ainsi filer sous la sidebar. Désactivé fermé / en overlay, sinon le
      `overflow-hidden` parent rognerait 8px de contenu à gauche. Transitionnée
      en phase avec la largeur de la sidebar (même durée/easing) : sinon la
      marge bascule instantanément pendant que la sidebar anime sur 200 ms, ce
      qui produit un saut visuel au lieu d'un mouvement continu.
    -->
    <main
      class="relative min-w-0 flex-1 overflow-hidden transition-[margin-left] duration-200 ease-in-out"
      :class="!isOverlay && layout.sidebarOpen ? '-ml-2' : ''"
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
