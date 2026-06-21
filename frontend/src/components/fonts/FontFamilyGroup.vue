<script setup lang="ts">
import {
  ref,
  computed,
  watch,
  nextTick,
  onMounted,
  onBeforeUnmount,
} from "vue";
import { ChevronUp, ChevronDown, RotateCcw } from "lucide-vue-next";
import { RouterLink } from "vue-router";
import { useI18n } from "vue-i18n";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import FontStyleRow from "./FontStyleRow.vue";
import EditablePreview from "./EditablePreview.vue";
import DeviceInstallSheet from "./DeviceInstallSheet.vue";
import type { FontFamily, FamilyMember } from "@/types/api";
import type { FontLayout, Typo } from "./types";

const props = defineProps<{
  family: FontFamily;
  typo: Typo;
  layout: FontLayout;
  observe: (el: Element, fontId: string) => void;
  unobserve: (el: Element) => void;
  getFontFamily: (fontId: string) => string;
  isFontReady: (fontId: string) => boolean;
}>();

const { t } = useI18n();

const open = ref(false);
const members = ref<FamilyMember[]>([]);
const loadingMembers = ref(false);
const loaded = ref(false);
const fetchError = ref(false);
const rootRef = ref<HTMLElement | null>(null);

// Crossfade aperçu famille → 1re graisse : refs pour mesurer le décalage
// vertical exact entre les deux mots et translater l'un pile sur l'autre.
const layerARef = ref<HTMLElement | null>(null);
const layerBRef = ref<HTMLElement | null>(null);
const familyWordRef = ref<{ getEl: () => HTMLElement | null } | null>(null);
const firstWeightRowRef = ref<{ getWordEl: () => HTMLElement | null } | null>(
  null,
);
const wordShift = ref(0);
// `revealed` pilote le glissement + fondu des graisses. Distinct de `open` : on
// le passe à true SEULEMENT après que les lignes soient montées (en position
// fermée) et `wordShift` mesuré, pour que le tout premier dépliage anime aussi.
const revealed = ref(false);
// `priming` coupe la transition des mots le temps de les poser en position
// fermée (sans glissement parasite), avant de révéler.
const priming = ref(false);

let abortController: AbortController | null = null;

const isMultiStyle = props.family.styleCount > 1;
const previewFontId = props.family.previewFont?.id ?? null;

// Tant que la fonte n'est pas résolue, on garde l'aperçu invisible (opacity 0)
// puis on le révèle en fondu : zéro flash fallback→vraie-fonte au scroll.
const previewReady = computed(
  () => !previewFontId || props.isFontReady(previewFontId),
);

const previewStyle = computed(() => ({
  fontFamily: previewFontId
    ? `'${props.getFontFamily(previewFontId)}', sans-serif`
    : "sans-serif",
  fontSize: `${props.typo.fontSize}px`,
  lineHeight: String(props.typo.lineHeight),
  letterSpacing: `${props.typo.letterSpacing}em`,
  opacity: previewReady.value ? 1 : 0,
}));

const foundry = computed(
  () => props.family.designer || props.family.manufacturer || "",
);
const category = computed(() => {
  const c = props.family.classification;
  return c ? c.charAt(0).toUpperCase() + c.slice(1) : "";
});
const format = computed(() =>
  (props.family.previewFont?.fileFormat || "").toUpperCase(),
);
const stylesLabel = computed(() =>
  t("fonts.styleCount", props.family.styleCount, {
    named: { n: props.family.styleCount },
  }),
);

const familyFontIds = computed(() =>
  members.value.length > 0
    ? members.value.map((m) => m.fontId)
    : previewFontId
      ? [previewFontId]
      : [],
);

// La 1re graisse occupe l'emplacement de tête (remplace l'aperçu famille) ;
// les graisses suivantes (2..N) se déplient dessous.
const firstMember = computed(() => members.value[0] ?? null);
const restMembers = computed(() => members.value.slice(1));

async function fetchMembers() {
  if (loaded.value || loadingMembers.value) return;
  abortController?.abort();
  abortController = new AbortController();

  loadingMembers.value = true;
  fetchError.value = false;
  try {
    const res = await apiFetch(`/api/font-families/${props.family.id}`, {
      signal: abortController.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    members.value = (data.members as FamilyMember[]).sort(
      (a, b) => a.sortOrder - b.sortOrder,
    );
    loaded.value = true;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") return;
    fetchError.value = true;
  } finally {
    loadingMembers.value = false;
  }
}

function retry() {
  loaded.value = false;
  fetchMembers();
}

function toggle() {
  if (!isMultiStyle) return;
  open.value = !open.value;
}

watch(open, (isOpen) => {
  if (!isOpen) {
    revealed.value = false;
    return;
  }
  if (loaded.value) revealNow();
  else fetchMembers(); // le glissement sera déclenché au chargement
});

// Décalage vertical entre le mot de l'aperçu famille et celui de la 1re
// graisse. Invariant des transforms (on retranche la position du wrapper), et
// indépendant de la taille de police (ne dépend que du « chrome » : label,
// paddings). Mesuré quand les lignes sont au repos (wordShift encore 0).
function measureWordShift() {
  const aWord = familyWordRef.value?.getEl();
  const bWord = firstWeightRowRef.value?.getWordEl();
  const aWrap = layerARef.value;
  const bWrap = layerBRef.value;
  if (!aWord || !bWord || !aWrap || !bWrap) return;
  const aRel =
    aWord.getBoundingClientRect().top - aWrap.getBoundingClientRect().top;
  const bRel =
    bWord.getBoundingClientRect().top - bWrap.getBoundingClientRect().top;
  wordShift.value = Math.max(0, bRel - aRel);
}

// Pose les mots en position fermée SANS transition (priming), puis, deux frames
// plus tard, réactive la transition et révèle → le glissement part bien de la
// position fermée (et non d'un état déjà presque ouvert).
function revealNow() {
  priming.value = true;
  revealed.value = false;
  nextTick(() => {
    requestAnimationFrame(() => {
      priming.value = false; // transition réactivée, mot toujours à −shift
      requestAnimationFrame(() => {
        if (open.value) revealed.value = true; // glissement → 0
      });
    });
  });
}

watch(firstMember, async (m) => {
  if (!m) return;
  priming.value = true; // pas de transition pendant la mesure/positionnement
  await nextTick(); // lignes montées (wordShift=0 → mot au repos)
  measureWordShift(); // mesure correcte ; le mot saute à −shift sans transition
  if (open.value) revealNow();
});

onMounted(() => {
  if (previewFontId && rootRef.value) {
    props.observe(rootRef.value, previewFontId);
  }
});

onBeforeUnmount(() => {
  abortController?.abort();
  if (rootRef.value) props.unobserve(rootRef.value);
});
</script>

<template>
  <li ref="rootRef" class="group">
    <!-- ── List layout ──────────────────────────────────────── -->
    <RouterLink
      v-if="layout === 'list'"
      :to="{ name: 'font-detail', params: { id: family.previewFont?.id } }"
      class="flex h-12 items-center gap-4 px-4 transition-colors hover:bg-accent sm:px-8"
    >
      <span class="size-1.5 flex-shrink-0 rounded-full bg-foreground-subtle" />
      <span
        class="min-w-0 flex-1 truncate text-[13px] sm:min-w-[180px] sm:flex-none"
        :style="{ fontFamily: previewStyle.fontFamily }"
      >
        {{ family.name }}
      </span>
      <span
        class="hidden min-w-[80px] flex-shrink-0 font-mono text-[10px] text-foreground-subtle sm:inline"
        >{{ category }}</span
      >
      <span
        class="hidden flex-shrink-0 font-mono text-[10px] text-foreground-subtle sm:inline"
        >{{ stylesLabel }}</span
      >
      <span
        v-if="format"
        class="hidden rounded bg-muted px-1.5 py-0.5 font-mono text-[9px] text-foreground-subtle sm:inline"
        >{{ format }}</span
      >
      <div class="hidden flex-1 sm:block" />
      <div
        class="opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100"
        @click.prevent.stop
      >
        <DeviceInstallSheet
          v-if="familyFontIds.length > 0"
          :font-ids="familyFontIds"
          trigger-variant="icon"
        />
      </div>
    </RouterLink>

    <!-- ── Specimen layout (default) ────────────────────────── -->
    <div v-else :style="{ '--word-shift': `${wordShift}px` }">
      <!-- En-tête : nom · styles · auteur (toujours visible). -->
      <div class="px-4 pt-7 sm:px-8">
        <div class="flex items-center gap-3 font-mono">
          <button
            v-if="isMultiStyle"
            type="button"
            class="group/toggle flex items-center gap-2"
            @click="toggle"
          >
            <ChevronUp
              v-if="open"
              class="size-3 flex-shrink-0 text-foreground transition-colors group-hover/toggle:text-brand"
              :stroke-width="2"
            />
            <ChevronDown
              v-else
              class="size-3 flex-shrink-0 text-muted-foreground transition-colors group-hover/toggle:text-brand"
              :stroke-width="2"
            />
            <span
              class="text-[11px] font-medium transition-colors group-hover/toggle:text-brand"
              >{{ family.name }}</span
            >
            <span class="text-foreground-subtle">·</span>
            <span class="text-[10px] text-muted-foreground">{{
              stylesLabel
            }}</span>
          </button>
          <RouterLink
            v-else
            :to="{
              name: 'font-detail',
              params: { id: family.previewFont?.id },
            }"
            class="text-[11px] font-medium"
          >
            {{ family.name }}
          </RouterLink>

          <span v-if="foundry" class="text-[10px] text-foreground-subtle">{{
            foundry
          }}</span>
          <div class="flex-1" />
          <div
            class="opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100"
          >
            <DeviceInstallSheet
              v-if="familyFontIds.length > 0"
              :font-ids="familyFontIds"
              trigger-variant="icon"
            />
          </div>
        </div>
      </div>

      <!--
        Emplacement de tête (hauteur d'une ligne de graisse). L'aperçu famille
        et la 1re graisse y sont superposés (grid stack). À l'ouverture, le mot
        famille glisse d'exactement --word-shift (mesuré) pour se poser pile sur
        le mot de la 1re graisse, en fondu croisé. Alignement parfait, sans saut.
      -->
      <div class="grid">
        <!--
          Aperçu famille (regular) : visible fermé. À l'ouverture il glisse de
          0 → +word-shift (mesuré) et s'efface en fondu.
        -->
        <div
          ref="layerARef"
          class="col-start-1 row-start-1 px-4 py-4 transition-[opacity,translate] duration-200 ease-out sm:px-8"
          :class="
            revealed
              ? 'pointer-events-none translate-y-[var(--word-shift)] opacity-0'
              : 'translate-y-0 opacity-100'
          "
        >
          <EditablePreview
            ref="familyWordRef"
            class="break-words leading-none transition-opacity duration-200"
            :style="previewStyle"
            :placeholder="family.name"
          />
        </div>

        <!--
          1re graisse : son FOND reste fixe (pas de translate → pas de blanc
          avec le bloc du dessous), seul son MOT glisse (slide-in) sur le même
          trajet que la famille pour rester superposé pile dessus. Fondu in.
        -->
        <div
          v-if="firstMember"
          ref="layerBRef"
          class="col-start-1 row-start-1 transition-opacity duration-200 ease-out"
          :class="revealed ? 'opacity-100' : 'pointer-events-none opacity-0'"
        >
          <FontStyleRow
            ref="firstWeightRowRef"
            :member="firstMember"
            :typo="typo"
            :family-name="family.name"
            :slide-in="revealed"
            :instant="priming"
            :observe="observe"
            :unobserve="unobserve"
            :get-font-family="getFontFamily"
            :is-font-ready="isFontReady"
          />
        </div>
      </div>

      <!--
        Graisses 2..N : la hauteur croît progressivement (grid 0fr → 1fr) pour
        pousser en douceur les familles du dessous ; le contenu glisse en
        translateY + fondu, exactement comme la 1re graisse.
      -->
      <div
        v-if="isMultiStyle"
        class="grid transition-[grid-template-rows] duration-200 ease-out"
        :class="open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'"
      >
        <div class="overflow-hidden">
          <!-- Squelette / erreur : visibles dès l'ouverture (retour de chargement). -->
          <div
            v-if="loadingMembers && members.length === 0"
            class="space-y-2 p-4"
          >
            <Skeleton
              v-for="i in Math.min(family.styleCount - 1, 4)"
              :key="i"
              class="h-12"
            />
          </div>

          <div
            v-else-if="fetchError"
            class="flex items-center gap-2 px-4 py-4 sm:px-8"
          >
            <span class="text-[11px] text-muted-foreground">{{
              t("fonts.loadError")
            }}</span>
            <Button variant="ghost" size="icon-sm" @click="retry">
              <RotateCcw class="size-3.5" />
            </Button>
          </div>

          <!--
            Fond gris CONTIGU : il ne translate pas (sinon il se décollerait du
            slot du haut → blanc). Seule l'opacité fait son apparition (sur
            `revealed`) ; chaque mot glisse à l'intérieur (slide-in), même
            animation que la 1re graisse, dès le 1er dépliage.
          -->
          <div
            v-else
            class="transition-opacity duration-200 ease-out"
            :class="revealed ? 'opacity-100' : 'opacity-0'"
          >
            <FontStyleRow
              v-for="member in restMembers"
              :key="member.fontId"
              :member="member"
              :typo="typo"
              :family-name="family.name"
              :slide-in="revealed"
              :instant="priming"
              :observe="observe"
              :unobserve="unobserve"
              :get-font-family="getFontFamily"
              :is-font-ready="isFontReady"
            />
          </div>
        </div>
      </div>
    </div>
  </li>
</template>
