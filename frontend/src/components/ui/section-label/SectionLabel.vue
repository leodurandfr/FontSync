<script setup lang="ts">
import type { HTMLAttributes } from "vue";
import { Primitive, type PrimitiveProps } from "reka-ui";
import { cn } from "@/lib/utils";

interface Props extends PrimitiveProps {
  class?: HTMLAttributes["class"];
}

const props = withDefaults(defineProps<Props>(), { as: "p" });
</script>

<template>
  <Primitive
    data-slot="section-label"
    :as="as"
    :as-child="asChild"
    :class="cn('text-[10px] font-medium text-muted-foreground', props.class)"
  >
    <slot />
  </Primitive>
</template>
