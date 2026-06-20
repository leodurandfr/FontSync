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
      Pas de v-if : on garde l'élément monté et on anime sa largeur « auto » via
      le truc grid 0fr↔1fr (seule façon d'animer une largeur auto en CSS) plus un
      fondu. L'inner clippe (`overflow-hidden`) sa bordure et son padding pendant
      le collapse, si bien que l'apparition reste synchro avec l'animation de la
      sidebar (200 ms, même easing) et pousse progressivement le reste de la barre.
    -->
    <div
      class="order-1 grid h-12 flex-shrink-0 overflow-hidden transition-[grid-template-columns,opacity] duration-200 ease-in-out sm:h-full"
      :class="
        layoutStore.sidebarOpen
          ? 'grid-cols-[0fr] opacity-0'
          : 'grid-cols-[1fr] opacity-100'
      "
    >
      <div
        class="flex items-center gap-3 overflow-hidden border-r border-separator pl-5 pr-3"
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

    <!-- 1 — Réglages typo (desktop uniquement) -->
    <div
      class="order-2 hidden h-full flex-shrink-0 items-center gap-3 border-r border-separator px-4 sm:flex"
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

    <!-- 2 — Layout switch -->
    <div
      class="order-3 flex h-12 flex-shrink-0 items-center border-l border-separator px-3 sm:order-3 sm:h-full sm:border-l-0 sm:border-r"
    >
      <SegmentedControl v-model="layout" :options="layoutOptions" />
    </div>

    <!-- 3 — Search -->
    <div
      class="order-2 flex h-12 min-w-0 flex-1 items-center gap-2 px-4 sm:order-4 sm:h-full sm:min-w-[148px]"
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
  </Panel>
</template>
