<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from "vue";
import { RouterLink } from "vue-router";
import { Download } from "lucide-vue-next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Font } from "@/types/api";

const props = defineProps<{
  font: Font;
  previewText: string;
  observe: (el: Element, fontId: string) => void;
  unobserve: (el: Element) => void;
  getFontFamily: (fontId: string) => string;
}>();

const cardRef = ref<HTMLElement | null>(null);

onMounted(() => {
  if (cardRef.value) {
    props.observe(cardRef.value, props.font.id);
  }
});

onBeforeUnmount(() => {
  if (cardRef.value) {
    props.unobserve(cardRef.value);
  }
});

function handleDownload(e: Event) {
  e.preventDefault();
  e.stopPropagation();
  const a = document.createElement("a");
  a.href = `/api/fonts/${props.font.id}/file`;
  a.download = props.font.originalFilename;
  a.click();
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

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
      :to="{ name: 'font-detail', params: { id: font.id } }"
      class="group flex flex-col rounded-xl border bg-card p-5 transition-colors hover:border-foreground/20"
    >
      <!-- Preview -->
      <div
        class="mb-4 h-20 overflow-hidden text-2xl leading-relaxed text-foreground/90"
        :style="{ fontFamily: `'${getFontFamily(font.id)}', sans-serif` }"
      >
        {{ previewText }}
      </div>

      <!-- Name -->
      <p
        class="font-semibold tracking-tight truncate"
        :title="font.familyName ?? font.originalFilename"
      >
        {{ font.familyName ?? font.originalFilename }}
      </p>
      <p class="text-sm text-muted-foreground truncate">
        {{ font.subfamilyName ?? font.fileFormat.toUpperCase() }}
      </p>

      <!-- Metadata row -->
      <div class="mt-3 flex flex-wrap items-center gap-1.5">
        <Badge v-if="font.classification" variant="secondary">
          {{
            CLASSIFICATION_LABELS[font.classification] ?? font.classification
          }}
        </Badge>
        <Badge v-if="font.isVariable" variant="outline"> Variable </Badge>
        <Badge v-if="font.glyphCount" variant="outline">
          {{ font.glyphCount }} glyphes
        </Badge>
      </div>

      <!-- Scripts -->
      <div
        v-if="font.supportedScripts?.length"
        class="mt-2 flex flex-wrap gap-1"
      >
        <span
          v-for="script in font.supportedScripts.slice(0, 4)"
          :key="script"
          class="text-[11px] text-muted-foreground capitalize"
        >
          {{ script
          }}{{
            font.supportedScripts.indexOf(script) <
            Math.min(font.supportedScripts.length, 4) - 1
              ? ","
              : ""
          }}
        </span>
        <span
          v-if="font.supportedScripts.length > 4"
          class="text-[11px] text-muted-foreground"
        >
          +{{ font.supportedScripts.length - 4 }}
        </span>
      </div>

      <!-- Footer -->
      <div class="mt-auto flex items-center justify-between pt-3">
        <span class="text-xs text-muted-foreground">
          {{ font.fileFormat.toUpperCase() }} ·
          {{ formatFileSize(font.fileSize) }}
        </span>
        <Button
          variant="ghost"
          size="icon-sm"
          class="opacity-0 group-hover:opacity-100 transition-opacity"
          @click="handleDownload"
        >
          <Download class="h-4 w-4" />
        </Button>
      </div>
    </RouterLink>
  </div>
</template>
