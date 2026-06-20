<script setup lang="ts">
import {
  Type,
  AlignLeft,
  ArrowUpDown,
  ArrowLeftRight,
  List,
  Search,
  PanelLeftOpen,
} from "lucide-vue-next";
import { useLayoutStore } from "@/stores/layout";
import { Panel } from "@/components/ui/panel";
import { TypoInput } from "@/components/ui/typo-input";
import {
  SegmentedControl,
  type SegmentedOption,
} from "@/components/ui/segmented";
import type { FontLayout } from "./types";

export type { FontLayout };

const layoutStore = useLayoutStore();

const previewText = defineModel<string>("previewText", { required: true });
const fontSize = defineModel<number>("fontSize", { required: true });
const lineHeight = defineModel<number>("lineHeight", { required: true });
const letterSpacing = defineModel<number>("letterSpacing", { required: true });
const layout = defineModel<FontLayout>("layout", { required: true });
const search = defineModel<string>("search", { required: true });

const layoutOptions: SegmentedOption<FontLayout>[] = [
  { value: "specimen", icon: Type, label: "Specimen" },
  { value: "body", icon: AlignLeft, label: "Body text" },
  { value: "list", icon: List, label: "List" },
];
</script>

<template>
  <Panel class="flex h-12 items-center overflow-hidden p-0">
    <!-- 0 — Réouverture sidebar (visible quand repliée) -->
    <button
      v-if="!layoutStore.sidebarOpen"
      type="button"
      class="flex h-full flex-shrink-0 items-center border-r border-separator px-3 text-foreground-subtle transition-colors hover:text-muted-foreground"
      aria-label="Ouvrir la sidebar"
      @click="layoutStore.setSidebarOpen(true)"
    >
      <PanelLeftOpen class="size-4" :stroke-width="1.5" />
    </button>

    <!-- 1 — Preview + typo -->
    <div
      class="flex h-full min-w-0 flex-1 items-center gap-3 border-r border-separator px-4"
    >
      <span
        class="flex-shrink-0 font-mono text-[9px] uppercase tracking-[0.12em] text-foreground-subtle"
      >
        Preview
      </span>
      <input
        v-model="previewText"
        type="text"
        placeholder="Type something…"
        class="min-w-0 flex-1 bg-transparent font-mono text-[11px] text-foreground outline-none placeholder:text-foreground-subtle"
      />
      <div
        class="flex flex-shrink-0 items-center gap-3 border-l border-separator pl-3"
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
      class="flex h-full flex-shrink-0 items-center border-r border-separator px-3"
    >
      <SegmentedControl v-model="layout" :options="layoutOptions" />
    </div>

    <!-- 3 — Search -->
    <div
      class="flex h-full min-w-[148px] flex-shrink-0 items-center gap-2 px-4"
    >
      <Search
        class="size-3 flex-shrink-0 text-foreground-subtle"
        :stroke-width="2"
      />
      <input
        v-model="search"
        type="search"
        placeholder="Search…"
        class="w-full bg-transparent font-mono text-[11px] text-foreground outline-none placeholder:text-foreground-subtle"
      />
    </div>
  </Panel>
</template>
