<script setup lang="ts">
import { computed } from "vue";
import {
  Type,
  AlignLeft,
  ArrowUpDown,
  ArrowLeftRight,
  List,
  Search,
  PanelLeftOpen,
} from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { useLayoutStore } from "@/stores/layout";
import { useFamiliesStore } from "@/stores/families";
import { showWindowControls } from "@/composables/useWindowControls";
import WindowControls from "@/components/layout/WindowControls.vue";
import { Panel } from "@/components/ui/panel";
import { TypoInput } from "@/components/ui/typo-input";
import {
  SegmentedControl,
  type SegmentedOption,
} from "@/components/ui/segmented";
import type { FontLayout } from "./types";

export type { FontLayout };

const { t } = useI18n();
const layoutStore = useLayoutStore();
const familiesStore = useFamiliesStore();

const fontSize = defineModel<number>("fontSize", { required: true });
const lineHeight = defineModel<number>("lineHeight", { required: true });
const letterSpacing = defineModel<number>("letterSpacing", { required: true });
const layout = defineModel<FontLayout>("layout", { required: true });
const search = defineModel<string>("search", { required: true });

const layoutOptions = computed<SegmentedOption<FontLayout>[]>(() => [
  { value: "specimen", icon: AlignLeft, label: t("toolbar.specimen") },
  { value: "list", icon: List, label: t("toolbar.list") },
]);
</script>

<template>
  <!--
    Desktop : une seule rangée [toggle | typo | layout | search]. Le texte
    d'aperçu n'est plus saisi ici : il s'édite en place dans chaque preview
    (voir `EditablePreview.vue`). Mobile (max-sm) : les réglages typo fins sont
    masqués, il reste [toggle | layout | search] sur une seule rangée.
  -->
  <Panel
    class="flex flex-wrap items-stretch overflow-hidden p-0 sm:h-12 sm:flex-nowrap sm:items-center"
    data-window-drag
  >
    <!-- 0 — Feux de fenêtre + réouverture sidebar (visibles quand repliée) -->
    <!--
      Monté uniquement quand la sidebar est repliée (v-if) : pas d'élément « vide »
      dans la barre quand la sidebar est affichée. L'apparition/disparition reste
      animée en largeur via une <Transition> qui interpole grid-template-columns
      0fr↔1fr (seule façon d'animer une largeur « auto » en CSS) + un fondu.
      L'inner clippe (overflow-hidden) sa bordure et son padding pendant le collapse,
      synchro avec l'animation de la sidebar (200 ms, même easing).
    -->
    <Transition
      enter-active-class="transition-[grid-template-columns,opacity] duration-200 ease-in-out"
      leave-active-class="transition-[grid-template-columns,opacity] duration-200 ease-in-out"
      enter-from-class="grid-cols-[0fr] opacity-0"
      enter-to-class="grid-cols-[1fr] opacity-100"
      leave-from-class="grid-cols-[1fr] opacity-100"
      leave-to-class="grid-cols-[0fr] opacity-0"
    >
      <div
        v-if="!layoutStore.sidebarOpen"
        class="order-1 grid h-12 flex-shrink-0 overflow-hidden sm:h-full"
      >
        <div
          class="flex min-w-0 items-center gap-3 overflow-hidden border-r border-separator pl-5 pr-3"
        >
          <WindowControls v-if="showWindowControls" />
          <button
            type="button"
            class="flex items-center text-foreground-subtle transition-colors hover:text-muted-foreground"
            :aria-label="t('sidebar.openSidebar')"
            @click="layoutStore.setSidebarOpen(true)"
          >
            <PanelLeftOpen class="size-4" :stroke-width="1.5" />
          </button>
        </div>
      </div>
    </Transition>

    <!-- 2 — Réglages typo (desktop uniquement) — début du groupe centré -->
    <div
      class="order-2 hidden h-full flex-shrink-0 items-center gap-5 border-r border-separator px-6 sm:order-3 sm:flex"
    >
      <TypoInput
        :icon="Type"
        v-model="fontSize"
        :min="10"
        :max="160"
        :step="1"
        suffix="px"
      />
      <TypoInput
        :icon="ArrowUpDown"
        v-model="lineHeight"
        :min="0.8"
        :max="3"
        :step="0.1"
        :digits="1"
      />
      <TypoInput
        :icon="ArrowLeftRight"
        v-model="letterSpacing"
        :min="-0.1"
        :max="0.3"
        :step="0.01"
        :digits="2"
      />
    </div>

    <!-- 3 — Layout switch (fin du groupe centré) -->
    <div
      class="order-3 flex h-12 flex-shrink-0 items-center border-l border-separator px-3 sm:order-4 sm:h-full sm:border-l-0 sm:px-6"
    >
      <SegmentedControl v-model="layout" :options="layoutOptions" />
    </div>

    <!-- 1 — Search (ancré à gauche) -->
    <div
      class="order-2 flex h-12 min-w-0 flex-1 items-center gap-2 px-4 sm:order-2 sm:h-full sm:max-w-[280px] sm:flex-1 sm:basis-0 sm:border-r sm:border-separator sm:px-6"
    >
      <Search
        class="size-3 flex-shrink-0 text-foreground-subtle"
        :stroke-width="2"
      />
      <input
        v-model="search"
        type="search"
        :placeholder="t('toolbar.search')"
        class="w-full bg-transparent font-mono text-[11px] text-foreground outline-none placeholder:text-foreground-subtle"
      />
    </div>

    <!-- 4 — Compteur de familles (desktop uniquement, ancré à droite) -->
    <div
      v-if="familiesStore.initialized"
      class="order-5 hidden h-full items-center justify-end whitespace-nowrap border-l border-separator px-6 font-mono text-[10px] tabular-nums text-foreground-subtle sm:flex sm:max-w-[280px] sm:flex-1 sm:basis-0"
    >
      {{
        t("toolbar.familyCount", familiesStore.total, {
          named: { n: familiesStore.total },
        })
      }}
    </div>
  </Panel>
</template>
