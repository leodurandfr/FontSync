<script setup lang="ts">
import { X, Minus } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { cn } from "@/lib/utils";
import { useWindowControls } from "@/composables/useWindowControls";

defineProps<{ class?: string }>();

const { t } = useI18n();
const { close, minimize, zoom } = useWindowControls();
</script>

<template>
  <!--
    Feux de circulation macOS : pastilles rouge/ambre/vert. Les symboles
    (×, −, ⤢) ne se révèlent qu'au survol du groupe, comme une fenêtre native.
    `group` + `group-hover` portent la révélation. `[-webkit-app-region:no-drag]`
    garde les boutons cliquables au sein d'une éventuelle zone de drag.
  -->
  <div :class="cn('group/traffic flex items-center gap-2', $props.class)">
    <button
      type="button"
      class="flex size-3 items-center justify-center rounded-full bg-[#ff5f57] text-black/60 transition-colors hover:brightness-95"
      :aria-label="t('window.close')"
      @click="close"
    >
      <X
        class="size-2 opacity-0 transition-opacity group-hover/traffic:opacity-100"
        :stroke-width="2.5"
      />
    </button>
    <button
      type="button"
      class="flex size-3 items-center justify-center rounded-full bg-[#febc2e] text-black/60 transition-colors hover:brightness-95"
      :aria-label="t('window.minimize')"
      @click="minimize"
    >
      <Minus
        class="size-2 opacity-0 transition-opacity group-hover/traffic:opacity-100"
        :stroke-width="2.5"
      />
    </button>
    <button
      type="button"
      class="flex size-3 items-center justify-center rounded-full bg-[#28c840] text-black/60 transition-colors hover:brightness-95"
      :aria-label="t('window.zoom')"
      @click="zoom"
    >
      <!-- Glyphe « zoom » natif : deux triangles opposés. -->
      <svg
        viewBox="0 0 10 10"
        class="size-2 opacity-0 transition-opacity group-hover/traffic:opacity-100"
        fill="currentColor"
        aria-hidden="true"
      >
        <path d="M1 1 H6 L1 6 Z" />
        <path d="M9 9 H4 L9 4 Z" />
      </svg>
    </button>
  </div>
</template>
