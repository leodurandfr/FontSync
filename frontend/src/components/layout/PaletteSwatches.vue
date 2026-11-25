<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { PALETTES, PALETTE_SWATCH, useTheme } from "@/composables/useTheme";

/**
 * Rangée de pastilles : chacune montre le duo de la palette (sidebar en
 * diagonale sur le fond) et un point de la couleur d'accent ; la palette
 * active est cerclée.
 */
const { t } = useI18n();
const { palette, setPalette } = useTheme();

function swatchStyle(p: (typeof PALETTES)[number]) {
  const c = PALETTE_SWATCH[p];
  return {
    background: `linear-gradient(135deg, ${c.sidebar} 50%, ${c.bg} 50%)`,
  };
}
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
      :style="swatchStyle(p)"
      @click="setPalette(p)"
    >
      <span
        class="absolute bottom-1 right-1 size-2 rounded-full"
        :style="{ backgroundColor: PALETTE_SWATCH[p].accent }"
      />
    </button>
  </div>
</template>
