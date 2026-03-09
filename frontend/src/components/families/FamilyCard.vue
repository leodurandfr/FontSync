<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from "vue";
import { RouterLink } from "vue-router";
import { Badge } from "@/components/ui/badge";
import type { FontFamily } from "@/types/api";

const props = defineProps<{
  family: FontFamily;
  previewText: string;
  observe: (el: Element, fontId: string) => void;
  unobserve: (el: Element) => void;
  getFontFamily: (fontId: string) => string;
}>();

const cardRef = ref<HTMLElement | null>(null);

onMounted(() => {
  if (cardRef.value && props.family.previewFont) {
    props.observe(cardRef.value, props.family.previewFont.id);
  }
});

onBeforeUnmount(() => {
  if (cardRef.value) {
    props.unobserve(cardRef.value);
  }
});

const CLASSIFICATION_LABELS: Record<string, string> = {
  serif: "Serif",
  "sans-serif": "Sans-serif",
  monospace: "Mono",
  display: "Display",
  handwriting: "Manuscrite",
  symbol: "Symbole",
};
</script>

<template>
  <div ref="cardRef">
    <RouterLink
      :to="{ name: 'family-detail', params: { id: family.id } }"
      class="group flex flex-col rounded-xl border bg-card p-5 transition-colors hover:border-foreground/20 min-h-[160px]"
    >
      <!-- Preview -->
      <div
        v-if="family.previewFont"
        class="mb-4 h-16 overflow-hidden text-2xl leading-relaxed text-foreground/90"
        :style="{
          fontFamily: `'${getFontFamily(family.previewFont.id)}', sans-serif`,
        }"
      >
        {{ previewText }}
      </div>
      <div
        v-else
        class="mb-4 flex h-16 items-center justify-center rounded-lg bg-muted/50 text-sm text-muted-foreground"
      >
        Aucun apercu
      </div>

      <!-- Name -->
      <p class="font-semibold tracking-tight truncate" :title="family.name">
        {{ family.name }}
      </p>
      <p class="text-sm text-muted-foreground">
        {{ family.styleCount }} style{{ family.styleCount !== 1 ? "s" : "" }}
      </p>

      <!-- Metadata row -->
      <div class="mt-3 flex flex-wrap items-center gap-1.5">
        <Badge v-if="family.classification" variant="secondary">
          {{
            CLASSIFICATION_LABELS[family.classification] ??
            family.classification
          }}
        </Badge>
        <Badge v-if="family.isAutoGrouped" variant="outline"> Auto </Badge>
      </div>

      <!-- Footer -->
      <div v-if="family.designer || family.manufacturer" class="mt-auto pt-3">
        <span class="text-xs text-muted-foreground">
          {{ family.designer ?? family.manufacturer }}
        </span>
      </div>
    </RouterLink>
  </div>
</template>
