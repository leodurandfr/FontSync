<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from "vue";
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
  if (isOpen && !loaded.value) fetchMembers();
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
    <div v-else>
      <div class="px-4 py-7 sm:px-8">
        <div class="mb-4 flex items-center gap-3 font-mono">
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
        <EditablePreview
          class="break-words leading-none transition-opacity duration-200"
          :style="previewStyle"
          :placeholder="family.name"
        />
      </div>

      <!-- Expanded styles -->
      <div v-if="isMultiStyle && open" class="border-t border-separator">
        <div
          v-if="loadingMembers && members.length === 0"
          class="space-y-2 p-4"
        >
          <Skeleton
            v-for="i in Math.min(family.styleCount, 4)"
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

        <FontStyleRow
          v-for="member in members"
          v-else
          :key="member.fontId"
          :member="member"
          :typo="typo"
          :family-name="family.name"
          :observe="observe"
          :unobserve="unobserve"
          :get-font-family="getFontFamily"
          :is-font-ready="isFontReady"
        />
      </div>
    </div>
  </li>
</template>
