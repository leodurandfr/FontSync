<script setup lang="ts">
import { ref, computed, nextTick } from "vue";
import type { Component } from "vue";

/**
 * Champ numérique compact « click-to-edit » du proto : affiche une valeur
 * monospace précédée d'une icône, devient un input au clic, clampe à [min, max].
 */
const props = withDefaults(
  defineProps<{
    icon: Component;
    min: number;
    max: number;
    step: number;
    digits?: number;
    suffix?: string;
  }>(),
  { digits: 0, suffix: "" },
);

const model = defineModel<number>({ required: true });

const editing = ref(false);
const inputRef = ref<HTMLInputElement | null>(null);

const display = computed(() =>
  props.digits > 0 ? model.value.toFixed(props.digits) : String(model.value),
);

async function startEdit() {
  editing.value = true;
  await nextTick();
  inputRef.value?.focus();
  inputRef.value?.select();
}

function commit(raw: string) {
  const n = parseFloat(raw);
  if (!isNaN(n)) model.value = Math.max(props.min, Math.min(props.max, n));
  editing.value = false;
}
</script>

<template>
  <div class="flex flex-shrink-0 items-center gap-1">
    <component
      :is="icon"
      class="size-3 flex-shrink-0 text-foreground-subtle"
      :stroke-width="1.5"
    />
    <input
      v-if="editing"
      ref="inputRef"
      type="number"
      :step="step"
      :value="display"
      class="w-12 appearance-none bg-transparent text-right font-mono text-[10px] tabular-nums text-foreground outline-none"
      @blur="commit(($event.target as HTMLInputElement).value)"
      @keydown.enter="commit(($event.target as HTMLInputElement).value)"
      @keydown.escape="editing = false"
    />
    <button
      v-else
      type="button"
      class="w-12 text-right font-mono text-[10px] tabular-nums text-muted-foreground transition-colors hover:text-foreground"
      @click="startEdit"
    >
      {{ display }}{{ suffix }}
    </button>
  </div>
</template>
