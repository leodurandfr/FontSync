<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import type { CSSProperties } from "vue";
import { Moon, Sun } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { useTheme } from "@/composables/useTheme";
import PaletteSwatches from "@/components/layout/PaletteSwatches.vue";

/**
 * Bouton de thème du pied de la sidebar.
 * - clic : bascule clair ↔ sombre ;
 * - survol prolongé (HOVER_MS) ou appui long (HOLD_MS) : ouvre une rangée de
 *   pastilles pour choisir la palette de couleurs de toute l'interface.
 */
const HOVER_MS = 1500;
const HOLD_MS = 450;
const LEAVE_MS = 250;

const { t } = useI18n();
const { dark, toggleTheme } = useTheme();

const open = ref(false);
const root = ref<HTMLElement | null>(null);
const popover = ref<HTMLElement | null>(null);
// La sidebar coupe ce qui déborde (overflow-hidden) : le panneau des palettes
// est téléporté dans <body> et placé en position fixe au-dessus du bouton.
const popoverStyle = ref<CSSProperties>({});

function show() {
  const rect = root.value?.getBoundingClientRect();
  if (rect) {
    popoverStyle.value = {
      left: `${Math.max(8, rect.left - 8)}px`,
      bottom: `${window.innerHeight - rect.top + 8}px`,
    };
  }
  open.value = true;
}

let hoverTimer: ReturnType<typeof setTimeout> | undefined;
let holdTimer: ReturnType<typeof setTimeout> | undefined;
let leaveTimer: ReturnType<typeof setTimeout> | undefined;
// Un appui long qui ouvre les palettes ne doit pas aussi basculer le thème.
let swallowClick = false;

function clearTimers() {
  clearTimeout(hoverTimer);
  clearTimeout(holdTimer);
  clearTimeout(leaveTimer);
}

function onEnter() {
  clearTimeout(leaveTimer);
  if (!open.value) hoverTimer = setTimeout(show, HOVER_MS);
}

function onLeave() {
  clearTimeout(hoverTimer);
  clearTimeout(holdTimer);
  leaveTimer = setTimeout(() => (open.value = false), LEAVE_MS);
}

function onPointerDown() {
  swallowClick = false;
  holdTimer = setTimeout(() => {
    swallowClick = true;
    show();
  }, HOLD_MS);
}

function onPointerUp() {
  clearTimeout(holdTimer);
}

function onClick() {
  if (swallowClick) {
    swallowClick = false;
    return;
  }
  clearTimeout(hoverTimer);
  toggleTheme();
}

function onDocumentPointerDown(event: PointerEvent) {
  const target = event.target as Node;
  if (
    open.value &&
    !root.value?.contains(target) &&
    !popover.value?.contains(target)
  ) {
    open.value = false;
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") open.value = false;
}

onMounted(() => {
  document.addEventListener("pointerdown", onDocumentPointerDown);
  document.addEventListener("keydown", onKeydown);
});

onBeforeUnmount(() => {
  clearTimers();
  document.removeEventListener("pointerdown", onDocumentPointerDown);
  document.removeEventListener("keydown", onKeydown);
});
</script>

<template>
  <div
    ref="root"
    class="relative"
    @pointerenter="onEnter"
    @pointerleave="onLeave"
  >
    <Teleport to="body">
      <Transition
        enter-active-class="transition duration-150 ease-out"
        enter-from-class="translate-y-1 opacity-0"
        leave-active-class="transition duration-100 ease-in"
        leave-to-class="translate-y-1 opacity-0"
      >
        <div
          v-if="open"
          ref="popover"
          class="fixed z-50 rounded-lg border border-panel-border bg-popover p-2 shadow-[0_4px_16px_rgba(0,0,0,0.12)]"
          :style="popoverStyle"
          role="dialog"
          @pointerenter="onEnter"
          @pointerleave="onLeave"
          :aria-label="t('theme.palette')"
        >
          <p
            class="mb-1.5 px-0.5 text-[10px] font-medium text-muted-foreground"
          >
            {{ t("theme.palette") }}
          </p>
          <PaletteSwatches />
        </div>
      </Transition>
    </Teleport>

    <button
      type="button"
      class="flex size-8 select-none items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
      :class="open && 'bg-accent text-accent-foreground'"
      :title="t('theme.quickSwitch')"
      :aria-label="t('theme.quickSwitch')"
      @pointerdown="onPointerDown"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @contextmenu.prevent
      @click="onClick"
    >
      <Sun v-if="dark" class="size-3.5" :stroke-width="1.5" />
      <Moon v-else class="size-3.5" :stroke-width="1.5" />
    </button>
  </div>
</template>
