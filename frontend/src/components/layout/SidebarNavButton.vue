<script setup lang="ts">
import { cn } from "@/lib/utils";

/**
 * Item de navigation de la sidebar : libellé + compteur optionnel,
 * fond `primary` quand sélectionné, survol `accent` sinon (proto NavBtn).
 */
withDefaults(
  defineProps<{
    label: string;
    count?: number;
    active?: boolean;
  }>(),
  { active: false },
);
defineEmits<{ click: [] }>();
</script>

<template>
  <button
    type="button"
    :aria-current="active ? 'page' : undefined"
    :class="
      cn(
        'mb-0.5 flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left transition-colors',
        active
          ? 'bg-primary text-primary-foreground'
          : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
      )
    "
    @click="$emit('click')"
  >
    <span class="truncate text-[11px]">{{ label }}</span>
    <span
      v-if="count !== undefined"
      class="text-[10px] tabular-nums opacity-50"
      >{{ count }}</span
    >
  </button>
</template>
