<script setup lang="ts">
import { Type } from "lucide-vue-next";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { useFamiliesStore } from "@/stores/families";

const previewText = defineModel<string>("previewText", { required: true });
const previewSize = defineModel<number>("previewSize", { required: true });

const familiesStore = useFamiliesStore();

function onSizeChange(value: number[] | undefined) {
  if (value && value.length > 0) previewSize.value = value[0]!;
}
</script>

<template>
  <div class="flex items-center gap-4 pb-4">
    <div class="flex items-center gap-2 w-36 shrink-0">
      <Slider
        :model-value="[previewSize ?? 16]"
        :min="8"
        :max="48"
        :step="1"
        class="flex-1"
        @update:model-value="onSizeChange"
      />
      <span class="text-xs text-muted-foreground w-8 text-right tabular-nums">
        {{ previewSize }}px
      </span>
    </div>
    <div class="relative flex-1">
      <Type
        class="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
      />
      <Input
        v-model="previewText"
        placeholder="Texte de prévisualisation..."
        class="pl-9 h-9"
      />
    </div>
    <span class="text-sm text-muted-foreground whitespace-nowrap">
      {{ familiesStore.total }} famille{{
        familiesStore.total !== 1 ? "s" : ""
      }}
    </span>
  </div>
</template>
