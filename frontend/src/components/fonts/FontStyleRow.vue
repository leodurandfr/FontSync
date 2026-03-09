<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from "vue";
import { RouterLink } from "vue-router";
import DeviceInstallSheet from "./DeviceInstallSheet.vue";
import type { FamilyMember } from "@/types/api";

const props = defineProps<{
  member: FamilyMember;
  previewText: string;
  previewSize: number;
  familyName: string;
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
  <div ref="rowRef" class="flex items-center border-t border-dashed">
    <RouterLink
      :to="{ name: 'font-detail', params: { id: member.fontId } }"
      class="group flex flex-1 min-w-0 flex-col gap-0.5 px-4 py-3 pl-10 transition-colors hover:bg-accent/50"
    >
      <!-- Style name -->
      <span class="text-sm text-muted-foreground truncate">
        {{ styleName(member) }}
      </span>

      <!-- Preview -->
      <span
        class="truncate leading-relaxed"
        :style="{
          fontSize: `${previewSize}px`,
          fontFamily: `'${getFontFamily(member.fontId)}', sans-serif`,
        }"
      >
        {{ previewText || familyName }}
      </span>
    </RouterLink>

    <div class="pr-3 shrink-0">
      <DeviceInstallSheet
        :font-ids="[member.fontId]"
        trigger-variant="icon"
      />
    </div>
  </div>
</template>
