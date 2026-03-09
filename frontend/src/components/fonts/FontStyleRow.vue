<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from "vue";
import { RouterLink } from "vue-router";
import type { FamilyMember } from "@/types/api";

const props = defineProps<{
  member: FamilyMember;
  previewText: string;
  observe: (el: Element, fontId: string) => void;
  unobserve: (el: Element) => void;
  getFontFamily: (fontId: string) => string;
}>();

const rowRef = ref<HTMLElement | null>(null);

onMounted(() => {
  if (rowRef.value) {
    props.observe(rowRef.value, props.member.fontId);
  }
});

onBeforeUnmount(() => {
  if (rowRef.value) {
    props.unobserve(rowRef.value);
  }
});

const WEIGHT_LABELS: Record<number, string> = {
  100: "Thin",
  200: "Extra-light",
  300: "Light",
  400: "Regular",
  500: "Medium",
  600: "Semi-bold",
  700: "Bold",
  800: "Extra-bold",
  900: "Black",
};

function styleName(member: FamilyMember): string {
  if (member.subfamilyName) return member.subfamilyName;
  const weight = member.weightClass
    ? (WEIGHT_LABELS[member.weightClass] ?? String(member.weightClass))
    : "Regular";
  return member.isItalic ? `${weight} Italic` : weight;
}
</script>

<template>
  <div ref="rowRef">
    <RouterLink
      :to="{ name: 'font-detail', params: { id: member.fontId } }"
      class="group flex items-center gap-4 px-4 py-3 transition-colors hover:bg-accent/50"
    >
      <!-- Style name -->
      <span class="w-40 shrink-0 truncate text-sm text-muted-foreground">
        {{ styleName(member) }}
      </span>

      <!-- Preview -->
      <span
        class="flex-1 truncate text-xl leading-relaxed"
        :style="{
          fontFamily: `'${getFontFamily(member.fontId)}', sans-serif`,
        }"
      >
        {{ previewText }}
      </span>
    </RouterLink>
  </div>
</template>
