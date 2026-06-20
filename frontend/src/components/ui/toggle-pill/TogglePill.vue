<script setup lang="ts">
import type { HTMLAttributes } from "vue";
import { cn } from "@/lib/utils";

/**
 * Petit pill bordé qui s'inverse en `primary` lorsqu'il est actif.
 * Réplique les boutons « Active / Collect » du proto (toolbar d'actions de ligne).
 */
interface Props {
  pressed?: boolean;
  class?: HTMLAttributes["class"];
}

withDefaults(defineProps<Props>(), { pressed: false });
defineEmits<{ click: [MouseEvent] }>();
</script>

<template>
  <button
    type="button"
    data-slot="toggle-pill"
    :data-pressed="pressed"
    :aria-pressed="pressed"
    :class="
      cn(
        'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 font-mono text-[10px] transition-all',
        pressed
          ? 'border-primary bg-primary text-primary-foreground'
          : 'border-border text-muted-foreground hover:text-foreground',
        $props.class,
      )
    "
    @click="$emit('click', $event)"
  >
    <slot />
  </button>
</template>
