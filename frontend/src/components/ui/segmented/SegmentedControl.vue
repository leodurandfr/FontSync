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
  <div data-slot="segmented" class="flex items-center gap-0.5">
    <button
      v-for="opt in options"
      :key="opt.value"
      type="button"
      :title="opt.label"
      :aria-label="opt.label"
      :aria-pressed="model === opt.value"
      :class="
        cn(
          'flex size-8 items-center justify-center rounded-lg transition-all',
          model === opt.value
            ? 'bg-primary text-primary-foreground'
            : 'text-foreground-subtle hover:bg-accent hover:text-muted-foreground',
        )
      "
      @click="model = opt.value"
    >
      <component :is="opt.icon" class="size-3.5" :stroke-width="1.5" />
    </button>
  </div>
</template>
