<script setup lang="ts">
import { Type } from "lucide-vue-next";
import { Input } from "@/components/ui/input";
import { useFamiliesStore } from "@/stores/families";

const previewText = defineModel<string>({ required: true });

const familiesStore = useFamiliesStore();
</script>

<template>
  <div class="flex items-center gap-4 pb-4">
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
