<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { PALETTES, PALETTE_SWATCH, useTheme } from "@/composables/useTheme";

/**
 * Rangée de pastilles : un carré de la couleur principale avec un rond de sa
 * complémentaire ; la palette active est cerclée.
 */
const { t } = useI18n();
const { palette, setPalette } = useTheme();
</script>

<template>
  <div class="flex items-center gap-1.5" role="radiogroup">
    <button
      v-for="p in PALETTES"
      :key="p"
      type="button"
      role="radio"
      :aria-checked="palette === p"
      :title="t(`theme.palettes.${p}`)"
      :aria-label="t(`theme.palettes.${p}`)"
      class="relative size-6 overflow-hidden rounded-md shadow-[inset_0_0_0_1px_rgba(0,0,0,0.12)] ring-offset-2 ring-offset-popover transition-transform hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      :class="palette === p && 'ring-2 ring-foreground/70'"
      :style="{ backgroundColor: PALETTE_SWATCH[p].main }"
      @click="setPalette(p)"
    >
      <span
        class="absolute inset-0 m-auto size-2.5 rounded-full"
        :style="{ backgroundColor: PALETTE_SWATCH[p].accent }"
      />
    </button>
  </div>
</template>
