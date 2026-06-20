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

const previewText = defineModel<string>("previewText", { required: true });
const fontSize = defineModel<number>("fontSize", { required: true });
const lineHeight = defineModel<number>("lineHeight", { required: true });
const letterSpacing = defineModel<number>("letterSpacing", { required: true });
const layout = defineModel<FontLayout>("layout", { required: true });
const search = defineModel<string>("search", { required: true });

const layoutOptions = computed<SegmentedOption<FontLayout>[]>(() => [
  { value: "specimen", icon: Type, label: t("toolbar.specimen") },
  { value: "body", icon: AlignLeft, label: t("toolbar.body") },
  { value: "list", icon: List, label: t("toolbar.list") },
]);
</script>

<template>
  <!--
    Desktop : une seule rangée [toggle | preview+typo | layout | search].
    Mobile (max-sm) : flex-wrap sur 2 rangées — rangée 1 [toggle | search |
    layout], rangée 2 (pleine largeur) le champ preview. Les réglages typo fins
    sont masqués sur mobile. Le ré-ordonnancement se fait via `order-*`.
  -->
  <Panel
    class="flex flex-wrap items-stretch overflow-hidden p-0 sm:h-12 sm:flex-nowrap sm:items-center"
  >
    <!-- 0 — Feux de fenêtre + réouverture sidebar (visibles quand repliée) -->
    <div
      v-if="!layoutStore.sidebarOpen"
      class="order-1 flex h-12 flex-shrink-0 items-center gap-3 border-r border-separator pl-5 pr-3 sm:h-full"
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

    <!-- 1 — Preview + typo -->
    <div
      class="order-last flex h-12 w-full min-w-0 items-center gap-3 border-t border-separator px-4 sm:order-2 sm:h-full sm:w-auto sm:flex-1 sm:border-t-0 sm:border-r"
    >
      <span
        class="hidden flex-shrink-0 font-mono text-[9px] uppercase tracking-[0.12em] text-foreground-subtle sm:inline"
      >
        {{ t("toolbar.preview") }}
      </span>
      <input
        v-model="previewText"
        type="text"
        :placeholder="t('toolbar.typeSomething')"
        class="min-w-0 flex-1 bg-transparent font-mono text-[11px] text-foreground outline-none placeholder:text-foreground-subtle"
      />
      <div
        class="hidden flex-shrink-0 items-center gap-3 border-l border-separator pl-3 sm:flex"
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
    </div>

    <!-- 2 — Layout switch -->
    <div
      class="order-3 flex h-12 flex-shrink-0 items-center border-l border-separator px-3 sm:order-3 sm:h-full sm:border-l-0 sm:border-r"
    >
      <SegmentedControl v-model="layout" :options="layoutOptions" />
    </div>

    <!-- 3 — Search -->
    <div
      class="order-2 flex h-12 min-w-0 flex-1 items-center gap-2 px-4 sm:order-4 sm:h-full sm:min-w-[148px] sm:flex-none"
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
