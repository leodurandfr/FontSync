<script setup lang="ts" generic="T extends string">
import type { Component } from "vue";
import { cn } from "@/lib/utils";

/**
 * Switch segmenté à icônes (proto : sélecteur de layout specimen/body/list).
 * Générique sur la valeur pour rester typé côté appelant.
 */
export interface SegmentedOption<V extends string> {
  value: V;
  icon: Component;
  label: string;
}

defineProps<{ options: SegmentedOption<T>[] }>();
const model = defineModel<T>({ required: true });
</script>

<template>
  <div
    data-slot="segmented"
    class="flex items-center gap-0.5 rounded-lg bg-segment-track p-0.5"
  >
    <button
      v-for="opt in options"
      :key="opt.value"
      type="button"
      :title="opt.label"
      :aria-label="opt.label"
      :aria-pressed="model === opt.value"
      :class="
        cn(
          'flex h-6 w-8 items-center justify-center rounded-md transition-all',
          model === opt.value
            ? 'bg-segment-thumb text-foreground shadow-[0_1px_2px_rgba(0,0,0,0.12)]'
            : 'text-muted-foreground hover:text-foreground',
        )
      "
      @click="model = opt.value"
    >
      <component :is="opt.icon" class="size-3.5" :stroke-width="1.5" />
    </button>
  </div>
</template>
