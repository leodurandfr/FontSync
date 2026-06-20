<script setup lang="ts">
import type { HTMLAttributes } from "vue";
import { Primitive, type PrimitiveProps } from "reka-ui";
import { cn } from "@/lib/utils";

interface Props extends PrimitiveProps {
  class?: HTMLAttributes["class"];
}

const props = withDefaults(defineProps<Props>(), { as: "div" });
</script>

<template>
  <Primitive
    data-slot="panel"
    :as="as"
    :as-child="asChild"
    :class="
      cn(
        'rounded-panel border border-panel-border bg-card text-card-foreground shadow-panel',
        props.class,
      )
    "
  >
    <slot />
  </Primitive>
</template>
