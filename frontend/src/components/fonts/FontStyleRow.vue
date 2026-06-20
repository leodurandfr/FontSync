<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import { RouterLink } from "vue-router";
import DeviceInstallSheet from "./DeviceInstallSheet.vue";
import EditablePreview from "./EditablePreview.vue";
import type { FamilyMember } from "@/types/api";
import type { Typo } from "./types";

const props = defineProps<{
  member: FamilyMember;
  typo: Typo;
  familyName: string;
  observe: (el: Element, fontId: string) => void;
  unobserve: (el: Element) => void;
  getFontFamily: (fontId: string) => string;
  isFontReady: (fontId: string) => boolean;
}>();

const rowRef = ref<HTMLElement | null>(null);

onMounted(() => {
  if (rowRef.value) props.observe(rowRef.value, props.member.fontId);
});
onBeforeUnmount(() => {
  if (rowRef.value) props.unobserve(rowRef.value);
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

const styleName = computed(() => {
  const m = props.member;
  if (m.subfamilyName) return m.subfamilyName;
  const weight = m.weightClass
    ? (WEIGHT_LABELS[m.weightClass] ?? String(m.weightClass))
    : "Regular";
  return m.isItalic ? `${weight} Italic` : weight;
});

const previewStyle = computed(() => ({
  fontFamily: `'${props.getFontFamily(props.member.fontId)}', sans-serif`,
  fontStyle: props.member.isItalic ? "italic" : "normal",
  fontSize: `${props.typo.fontSize}px`,
  lineHeight: String(props.typo.lineHeight),
  letterSpacing: `${props.typo.letterSpacing}em`,
  opacity: props.isFontReady(props.member.fontId) ? 1 : 0,
}));
</script>

<template>
  <div
    ref="rowRef"
    class="group/style border-t border-separator bg-muted px-8 py-6"
  >
    <div class="mb-4 flex items-center gap-3 font-mono">
      <RouterLink
        :to="{ name: 'font-detail', params: { id: member.fontId } }"
        class="text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
        >{{ styleName }}</RouterLink
      >
      <span class="text-foreground-subtle">·</span>
      <span class="text-[10px] text-foreground-subtle">{{ familyName }}</span>
      <div class="flex-1" />
      <div class="opacity-0 transition-opacity group-hover/style:opacity-100">
        <DeviceInstallSheet
          :font-ids="[member.fontId]"
          trigger-variant="icon"
        />
      </div>
    </div>
    <EditablePreview
      class="block break-words leading-none transition-opacity duration-200"
      :style="previewStyle"
      :placeholder="familyName"
    />
  </div>
</template>
