<script setup lang="ts">
import { ref, computed } from "vue";
import { RouterLink } from "vue-router";
import { useI18n } from "vue-i18n";
import { ArrowUpRight, Download } from "lucide-vue-next";
import { Button } from "@/components/ui/button";
import { downloadFromApi } from "@/lib/download";
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

const { t } = useI18n();

const wordRef = ref<InstanceType<typeof EditablePreview> | null>(null);

async function handleDownload() {
  try {
    await downloadFromApi(
      `/api/fonts/${props.member.fontId}/file`,
      props.member.originalFilename,
    );
  } catch {
    // Échec réseau / 401 (la saisie du token reprend la main).
  }
}

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
  <!--
    pb-8 (32px sous le mot) au lieu de py-4 : même respiration basse qu'une carte
    repliée (py-4 16 + pb-4 16). NB : le parent (FontFamilyGroup) compense cet
    excédent (32−16 = 16) sur le spacer de l'emplacement de tête pour que la 1re
    graisse, posée en `absolute`, ne soit pas clippée.
  -->
  <div
    class="group/style border-t border-separator bg-font-preview px-8 pb-8 pt-4"
  >
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
        <span class="text-[11px] font-medium text-muted-foreground">{{
          styleName
        }}</span>
        <div class="flex-1" />
        <div
          class="flex items-center gap-1 opacity-0 transition-opacity group-hover/style:opacity-100"
        >
          <Button
            variant="ghost"
            size="icon-sm"
            :aria-label="t('common.download')"
            @click="handleDownload"
          >
            <Download class="h-3.5 w-3.5" />
          </Button>
          <DeviceInstallSheet
            :font-ids="[member.fontId]"
            trigger-variant="icon"
          />
          <Button as-child variant="ghost" size="icon-sm">
            <RouterLink
              :to="{ name: 'font-detail', params: { id: member.fontId } }"
              :aria-label="t('fontDetail.openDetails')"
            >
              <ArrowUpRight class="h-3.5 w-3.5" />
            </RouterLink>
          </Button>
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
