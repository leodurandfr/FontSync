<script setup lang="ts">
import { computed, ref } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { useI18n } from "vue-i18n";
import { PanelLeftClose, Settings, Upload } from "lucide-vue-next";
import { SectionLabel } from "@/components/ui/section-label";
import { Panel } from "@/components/ui/panel";
import SidebarNavButton from "./SidebarNavButton.vue";
import ThemeToggle from "./ThemeToggle.vue";
import UploadDialog from "@/components/fonts/UploadDialog.vue";
import { useLayoutStore } from "@/stores/layout";
import { useFamiliesStore } from "@/stores/families";
import { useFamilyFiltersStore } from "@/stores/familyFilters";
import { useWsStore } from "@/stores/ws";

const { t } = useI18n();

const layout = useLayoutStore();
const familiesStore = useFamiliesStore();
const filtersStore = useFamilyFiltersStore();
const wsStore = useWsStore();
const route = useRoute();

const CATEGORIES = [
  "serif",
  "sans-serif",
  "monospace",
  "display",
  "handwriting",
  "symbol",
] as const;

const onSettings = computed(() => route.path.startsWith("/settings"));
const connected = computed(() => wsStore.status === "connected");

function selectAll() {
  filtersStore.classification = undefined;
}

function selectCategory(value: string) {
  filtersStore.classification =
    filtersStore.classification === value ? undefined : value;
}

// ── Resize ────────────────────────────────────────────────────
// Pendant un drag actif, on coupe la transition de largeur : sinon chaque
// pointermove est animé sur 200 ms et la <main> poursuit le curseur avec du
// retard. La transition reste en place pour le toggle open/close.
const resizing = ref(false);

function startResize(e: PointerEvent) {
  e.preventDefault();
  const startX = e.clientX;
  const startWidth = layout.sidebarWidth;
  resizing.value = true;

  const onMove = (ev: PointerEvent) => {
    layout.setSidebarWidth(startWidth + ev.clientX - startX);
  };
  const onUp = () => {
    resizing.value = false;
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
}
</script>

<template>
  <!--
    Desktop : la sidebar pousse le contenu (largeur réservée, redimensionnable).
    Mobile (max-sm) : drawer fixe en surimpression au-dessus du backdrop, de
    largeur fixe, qui coulisse via translate-x. `!w-` (important) écrase la
    largeur inline pour que `-translate-x-full` masque toujours tout le panneau.
  -->
  <div
    class="z-50 flex-shrink-0 ease-in-out max-sm:fixed max-sm:inset-y-0 max-sm:left-0 max-sm:w-[min(288px,82vw)]!"
    :class="[
      resizing ? '' : 'transition-all duration-200',
      layout.sidebarOpen
        ? 'max-sm:translate-x-0'
        : 'max-sm:pointer-events-none max-sm:-translate-x-full',
    ]"
    :style="{
      width: layout.sidebarOpen ? `${layout.sidebarWidth + 12}px` : '0',
    }"
  >
    <Panel
      as="aside"
      class="relative m-3 flex h-[calc(100vh-24px)] flex-col overflow-hidden transition-opacity duration-200 max-sm:w-[min(288px,82vw)]!"
      :style="{
        width: `${layout.sidebarWidth}px`,
        opacity: layout.sidebarOpen ? 1 : 0,
      }"
    >
      <!-- Header -->
      <div
        class="flex h-14 flex-shrink-0 items-center justify-between border-b border-separator px-5"
      >
        <div class="flex min-w-0 items-center gap-2">
          <span
            class="size-1.5 flex-shrink-0 rounded-full"
            :class="connected ? 'bg-emerald-500' : 'bg-amber-500'"
            :title="
              connected ? t('common.connected') : t('sidebar.reconnecting')
            "
          />
          <span
            class="truncate text-[11px] font-semibold uppercase tracking-[0.12em]"
          >
            FontSync
          </span>
        </div>
        <button
          type="button"
          class="-mr-1 flex-shrink-0 p-1 text-foreground-subtle transition-colors hover:text-muted-foreground"
          :aria-label="t('sidebar.collapse')"
          @click="layout.setSidebarOpen(false)"
        >
          <PanelLeftClose class="size-4" :stroke-width="1.5" />
        </button>
      </div>

      <!-- Nav -->
      <nav class="flex-1 overflow-y-auto px-3 py-3 [scrollbar-width:none]">
        <SectionLabel class="px-2 pb-1.5">{{
          t("sidebar.library")
        }}</SectionLabel>
        <SidebarNavButton
          :label="t('sidebar.allFonts')"
          :count="familiesStore.total"
          :active="!filtersStore.classification"
          @click="selectAll"
        />

        <SectionLabel class="px-2 pb-1.5 pt-4">{{
          t("sidebar.categories")
        }}</SectionLabel>
        <SidebarNavButton
          v-for="cat in CATEGORIES"
          :key="cat"
          :label="t(`categories.${cat}`)"
          :active="filtersStore.classification === cat"
          @click="selectCategory(cat)"
        />
      </nav>

      <!-- Footer -->
      <div
        class="flex flex-shrink-0 items-center gap-1 border-t border-separator px-3 py-3"
      >
        <UploadDialog>
          <button
            type="button"
            class="flex flex-1 items-center gap-2 rounded-lg px-2 py-1.5 text-muted-foreground transition-colors hover:bg-accent"
          >
            <Upload class="size-3.5" :stroke-width="1.5" />
            <span class="text-[11px]">{{ t("sidebar.upload") }}</span>
          </button>
        </UploadDialog>

        <RouterLink
          to="/settings"
          class="flex flex-1 items-center gap-2 rounded-lg px-2 py-1.5 transition-colors"
          :class="
            onSettings
              ? 'bg-accent text-accent-foreground'
              : 'text-muted-foreground hover:bg-accent'
          "
        >
          <Settings class="size-3.5" :stroke-width="1.5" />
          <span class="text-[11px]">{{ t("sidebar.settings") }}</span>
        </RouterLink>

        <ThemeToggle />
      </div>

      <!-- Resize handle (desktop uniquement) -->
      <div
        class="group absolute bottom-0 right-0 top-0 flex w-3 cursor-col-resize items-center justify-center max-sm:hidden"
        @pointerdown="startResize"
      >
        <div
          class="h-10 w-px rounded-full bg-foreground-subtle opacity-0 transition-opacity group-hover:opacity-100"
        />
      </div>
    </Panel>
  </div>
</template>
