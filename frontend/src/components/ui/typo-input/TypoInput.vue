<script setup lang="ts">
import { ref, computed, nextTick } from "vue";
import type { Component } from "vue";
import {
  HoverCardRoot,
  HoverCardTrigger,
  HoverCardPortal,
  HoverCardContent,
} from "reka-ui";
import { Slider } from "@/components/ui/slider";

/**
 * Champ numérique compact « click-to-edit » du proto : affiche une valeur
 * monospace précédée d'une icône, devient un input au clic, clampe à [min, max].
 * Au survol, une petite box apparaît (translate + opacity + scale, comme le
 * dropdown de thème) avec un range-slider lié à la même valeur.
 */
const props = withDefaults(
  defineProps<{
    icon: Component;
    min: number;
    max: number;
    step: number;
    digits?: number;
    suffix?: string;
    disabled?: boolean;
  }>(),
  { digits: 0, suffix: "", disabled: false },
);

const model = defineModel<number>({ required: true });

const editing = ref(false);
const inputRef = ref<HTMLInputElement | null>(null);

const display = computed(() =>
  props.digits > 0 ? model.value.toFixed(props.digits) : String(model.value),
);

const sliderValue = computed({
  get: () => [model.value],
  set: (v: number[] | undefined) => {
    if (v?.[0] !== undefined) model.value = v[0];
  },
});

const fmt = (n: number) =>
  props.digits > 0 ? n.toFixed(props.digits) : String(n);

async function startEdit() {
  if (props.disabled) return;
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
  <HoverCardRoot
    :open-delay="80"
    :close-delay="120"
    :open="disabled ? false : undefined"
  >
    <HoverCardTrigger
      as="div"
      class="flex flex-shrink-0 items-center gap-1 transition-opacity"
      :class="disabled ? 'pointer-events-none opacity-40' : ''"
    >
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
        class="w-9 appearance-none bg-transparent text-right font-mono text-[10px] tabular-nums text-foreground outline-none"
        @blur="commit(($event.target as HTMLInputElement).value)"
        @keydown.enter="commit(($event.target as HTMLInputElement).value)"
        @keydown.escape="editing = false"
      />
      <button
        v-else
        type="button"
        :disabled="disabled"
        class="w-9 text-right font-mono text-[10px] tabular-nums text-muted-foreground transition-colors hover:text-foreground"
        @click="startEdit"
      >
        {{ display }}{{ suffix }}
      </button>
    </HoverCardTrigger>

    <!-- Box hover avec range-slider (portal → pas de clipping par overflow) -->
    <HoverCardPortal>
      <HoverCardContent
        side="bottom"
        align="center"
        :side-offset="8"
        class="z-50 origin-(--reka-hover-card-content-transform-origin) rounded-md border bg-popover text-popover-foreground shadow-md data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=top]:slide-in-from-bottom-2"
      >
        <div class="flex w-44 items-center gap-2 px-3 py-2.5">
          <span class="font-mono text-[9px] text-foreground-subtle">
            {{ fmt(min) }}
          </span>
          <Slider
            v-model="sliderValue"
            :min="min"
            :max="max"
            :step="step"
            class="flex-1"
          />
          <span class="font-mono text-[9px] text-foreground-subtle">
            {{ fmt(max) }}
          </span>
        </div>
      </HoverCardContent>
    </HoverCardPortal>
  </HoverCardRoot>
</template>
