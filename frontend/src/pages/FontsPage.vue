<script setup lang="ts">
import { ref } from "vue";
import FilterPanel from "@/components/fonts/FilterPanel.vue";
import PreviewToolbar from "@/components/fonts/PreviewToolbar.vue";
import FontGrid from "@/components/fonts/FontGrid.vue";

const previewText = ref("Portez ce vieux whisky au juge blond qui fume");
</script>

<template>
  <div class="flex h-[calc(100vh-3.5rem)] overflow-hidden">
    <FilterPanel />

    <main class="flex-1 overflow-y-auto p-6">
      <div class="mb-6">
        <h1 class="text-3xl font-bold tracking-tight">Polices</h1>
        <p class="text-muted-foreground mt-1">
          Parcourez et gérez votre bibliothèque de polices.
        </p>
      </div>

      <PreviewToolbar v-model="previewText" />
      <FontGrid :preview-text="previewText" />
    </main>
  </div>
</template>
