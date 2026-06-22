<script setup lang="ts">
import { ref, computed } from "vue";
import { RouterLink } from "vue-router";
import DeviceInstallSheet from "./DeviceInstallSheet.vue";
import EditablePreview from "./EditablePreview.vue";
import type { FamilyMember } from "@/types/api";
import type { Typo } from "./types";

// Le chargement de la fonte est géré par le parent (`preload`/`release`) : la
// ligne est clippée (overflow-hidden) donc invisible pour l'IntersectionObserver,
// et elle ne doit pas retenir de référence qui empêcherait le déchargement.
const props = withDefaults(
  defineProps<{
    member: FamilyMember;
    typo: Typo;
    familyName: string;
    getFontFamily: (fontId: string) => string;
    isFontReady: (fontId: string) => boolean;
    // Glissement du mot : false = posé en haut (−word-shift), true = en place.
    slideIn?: boolean;
    // true = positionnement instantané (sans transition), pour amorcer l'état
    // fermé avant de déclencher le glissement.
    instant?: boolean;
  }>(),
  { slideIn: true, instant: false },
);

const wordRef = ref<InstanceType<typeof EditablePreview> | null>(null);

// Expose l'élément du mot pour que le parent aligne le crossfade dessus.
defineExpose({ getWordEl: () => wordRef.value?.getEl() ?? null });

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
  <div class="group/style border-t border-separator bg-font-preview px-8 py-4">
    <!-- Le fond gris (ci-dessus) reste fixe ; label + mot glissent ensemble. -->
    <div
      :class="[
        instant ? '' : 'transition-[translate] duration-200 ease-out',
        slideIn
          ? 'translate-y-0'
          : 'translate-y-[calc(var(--word-shift)_*_-1)]',
      ]"
    >
      <div class="mb-1 flex items-center gap-3 font-mono">
        <RouterLink
          :to="{ name: 'font-detail', params: { id: member.fontId } }"
          class="text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
          >{{ styleName }}</RouterLink
        >
        <div class="flex-1" />
        <div class="opacity-0 transition-opacity group-hover/style:opacity-100">
          <DeviceInstallSheet
            :font-ids="[member.fontId]"
            trigger-variant="icon"
          />
        </div>
      </div>
      <EditablePreview
        ref="wordRef"
        class="block break-words leading-none transition-opacity duration-200"
        :style="previewStyle"
        :placeholder="familyName"
      />
    </div>
  </div>
</template>
