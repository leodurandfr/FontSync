<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { RouterLink } from "vue-router";
import { useI18n } from "vue-i18n";
import {
  ArrowLeft,
  Download,
  ChevronLeft,
  ChevronRight,
  Upload,
  Calendar,
  Monitor,
  Type,
  ArrowLeftRight,
  UnfoldVertical,
} from "lucide-vue-next";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Panel } from "@/components/ui/panel";
import { SectionLabel } from "@/components/ui/section-label";
import { TypoInput } from "@/components/ui/typo-input";
import DeviceInstallSheet from "@/components/fonts/DeviceInstallSheet.vue";
import { apiFetch } from "@/lib/api";
import { useLocale } from "@/composables/useLocale";
import type { Font } from "@/types/api";

const props = defineProps<{ id: string }>();

const { t, te } = useI18n();
const { dateLocale } = useLocale();

function classificationLabel(c: string): string {
  const key = `fontDetail.classification.${c}`;
  return te(key) ? t(key) : c;
}

function sourceLabel(s: string): string {
  const key = `fontDetail.sources.${s}`;
  return te(key) ? t(key) : s;
}

const font = ref<Font | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const fontLoaded = ref(false);
const previewText = ref("Portez ce vieux whisky au juge blond qui fume");
const previewSize = ref(40);
const previewLeading = ref(1.3);
const previewTracking = ref(0);
const glyphPage = ref(0);

let fontFace: FontFace | null = null;
let fetchAbort: AbortController | null = null;

const fontFamily = computed(() => `detail-${props.id}`);

const WATERFALL_SIZES = [12, 16, 20, 24, 32, 48, 64, 72];

const GLYPH_CHARS = [
  ..."ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
  ..."0123456789",
  ..."!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",
  ..."ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞß",
  ..."àáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ",
];

const GLYPHS_PER_PAGE = 80;

const glyphPages = computed(() => {
  const pages: string[][] = [];
  for (let i = 0; i < GLYPH_CHARS.length; i += GLYPHS_PER_PAGE) {
    pages.push(GLYPH_CHARS.slice(i, i + GLYPHS_PER_PAGE));
  }
  return pages;
});

const currentGlyphs = computed(() => glyphPages.value[glyphPage.value] ?? []);
const totalGlyphPages = computed(() => glyphPages.value.length);

const WEIGHT_LABELS: Record<number, string> = {
  100: "Thin",
  200: "Extra Light",
  300: "Light",
  400: "Regular",
  500: "Medium",
  600: "Semi Bold",
  700: "Bold",
  800: "Extra Bold",
  900: "Black",
};

async function fetchFont() {
  fetchAbort?.abort();
  fetchAbort = new AbortController();
  loading.value = true;
  error.value = null;
  try {
    const res = await apiFetch(`/api/fonts/${props.id}`, {
      signal: fetchAbort.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    font.value = await res.json();
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") return;
    error.value = e instanceof Error ? e.message : t("common.unknownError");
  } finally {
    loading.value = false;
  }
}

async function loadFontFace() {
  try {
    // `/api/fonts/:id/preview` exige le token : on récupère les octets avec
    // `apiFetch` (en-tête `Authorization`) puis on construit la `FontFace` à
    // partir du buffer — `url(...)` ne peut pas porter d'en-tête d'auth.
    const res = await apiFetch(`/api/fonts/${props.id}/preview`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const buffer = await res.arrayBuffer();
    fontFace = new FontFace(fontFamily.value, buffer, { display: "swap" });
    await fontFace.load();
    document.fonts.add(fontFace);
    fontLoaded.value = true;
  } catch {
    fontFace = null;
  }
}

async function handleDownload() {
  if (!font.value) return;
  // Téléchargement via blob authentifié : un `<a href>` direct ne peut pas
  // porter le token sur une route `/api/*` protégée.
  try {
    const res = await apiFetch(`/api/fonts/${props.id}/file`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = font.value.originalFilename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch {
    // Échec réseau / 401 (la saisie du token reprend la main).
  }
}

function isSafeUrl(url: string | null): boolean {
  if (!url) return false;
  try {
    const parsed = new URL(url, window.location.origin);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString(dateLocale.value, {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

onMounted(async () => {
  await fetchFont();
  if (font.value) loadFontFace();
});

onUnmounted(() => {
  fetchAbort?.abort();
  if (fontFace) {
    document.fonts.delete(fontFace);
    fontFace = null;
  }
});
</script>

<template>
  <div class="scrollbar-thin h-full overflow-y-auto">
    <!-- Loading -->
    <div
      v-if="loading"
      class="mx-auto max-w-4xl space-y-8 px-4 py-8 sm:px-8 sm:py-10"
    >
      <Skeleton class="h-8 w-64" />
      <Skeleton class="h-5 w-40" />
      <Skeleton class="h-40 w-full rounded-panel" />
      <div class="grid gap-4 sm:grid-cols-2">
        <Skeleton v-for="i in 6" :key="i" class="h-10" />
      </div>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="mx-auto max-w-4xl px-4 py-8 sm:px-8 sm:py-10">
      <Panel class="p-12 text-center">
        <p class="text-sm text-foreground">{{ t("fontDetail.cannotLoad") }}</p>
        <p class="mt-1 font-mono text-[10px] text-foreground-subtle">
          {{ error }}
        </p>
        <div class="mt-4 flex justify-center gap-3">
          <Button variant="outline" as-child>
            <RouterLink :to="{ name: 'fonts' }">
              <ArrowLeft class="mr-2 h-4 w-4" />
              {{ t("common.back") }}
            </RouterLink>
          </Button>
          <Button @click="fetchFont">{{ t("common.retry") }}</Button>
        </div>
      </Panel>
    </div>

    <!-- Content -->
    <div
      v-else-if="font"
      class="mx-auto max-w-4xl space-y-10 px-4 py-8 sm:px-8 sm:py-10"
    >
      <!-- Header -->
      <header>
        <RouterLink
          :to="{ name: 'fonts' }"
          class="mb-5 inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.12em] text-foreground-subtle transition-colors hover:text-foreground"
        >
          <ArrowLeft class="size-3" :stroke-width="2" />
          {{ t("fontDetail.fonts") }}
        </RouterLink>

        <div
          class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between"
        >
          <div class="min-w-0">
            <h1 class="truncate text-3xl font-semibold tracking-tight">
              {{ font.familyName ?? font.originalFilename }}
            </h1>
            <div class="mt-2 flex flex-wrap items-center gap-2 font-mono">
              <span class="text-[11px] text-muted-foreground">
                {{ font.subfamilyName ?? font.fileFormat.toUpperCase() }}
              </span>
              <span
                v-if="font.classification"
                class="rounded bg-muted px-1.5 py-0.5 text-[9px] text-foreground-subtle"
              >
                {{ classificationLabel(font.classification) }}
              </span>
              <span
                v-if="font.isVariable"
                class="rounded bg-muted px-1.5 py-0.5 text-[9px] text-foreground-subtle"
              >
                {{ t("common.variable") }}
              </span>
            </div>
          </div>
          <div class="flex flex-shrink-0 items-center gap-2">
            <DeviceInstallSheet :font-ids="[id]" />

            <Button @click="handleDownload">
              <Download class="mr-2 h-4 w-4" />
              {{ t("common.download") }}
            </Button>
          </div>
        </div>
      </header>

      <!-- Preview -->
      <section>
        <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
          <SectionLabel>{{ t("fontDetail.preview") }}</SectionLabel>
          <div class="flex items-center gap-3">
            <TypoInput
              :icon="Type"
              v-model="previewSize"
              :min="12"
              :max="160"
              :step="1"
              suffix="px"
            />
            <TypoInput
              :icon="UnfoldVertical"
              v-model="previewLeading"
              :min="0.8"
              :max="2.4"
              :step="0.05"
              :digits="2"
            />
            <TypoInput
              :icon="ArrowLeftRight"
              v-model="previewTracking"
              :min="-0.1"
              :max="0.3"
              :step="0.01"
              :digits="2"
            />
          </div>
        </div>
        <Panel class="overflow-hidden p-0">
          <input
            v-model="previewText"
            type="text"
            :placeholder="t('fontDetail.inputPlaceholder')"
            class="w-full border-b border-separator bg-transparent px-6 py-3 font-mono text-[11px] text-foreground outline-none placeholder:text-foreground-subtle"
          />
          <div
            class="select-text break-words p-6"
            :style="{
              fontSize: `${previewSize}px`,
              lineHeight: previewLeading,
              letterSpacing: `${previewTracking}em`,
              fontFamily: fontLoaded
                ? `'${fontFamily}', sans-serif`
                : 'sans-serif',
            }"
          >
            {{ previewText }}
          </div>
        </Panel>
      </section>

      <!-- Waterfall -->
      <section>
        <SectionLabel class="mb-3">{{
          t("fontDetail.waterfall")
        }}</SectionLabel>
        <Panel class="space-y-4 p-6">
          <div
            v-for="size in WATERFALL_SIZES"
            :key="size"
            class="flex items-baseline gap-4"
          >
            <span
              class="w-10 shrink-0 text-right font-mono text-[10px] text-foreground-subtle"
            >
              {{ size }}px
            </span>
            <span
              class="min-w-0 select-text break-words"
              :style="{
                fontSize: `${size}px`,
                lineHeight: 1.3,
                fontFamily: fontLoaded
                  ? `'${fontFamily}', sans-serif`
                  : 'sans-serif',
              }"
            >
              {{ previewText }}
            </span>
          </div>
        </Panel>
      </section>

      <!-- Metadata -->
      <section>
        <SectionLabel class="mb-3">{{ t("fontDetail.metadata") }}</SectionLabel>
        <Panel class="p-6">
          <dl class="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
            <div v-if="font.designer">
              <SectionLabel as="dt">{{
                t("fontDetail.designer")
              }}</SectionLabel>
              <dd class="mt-1 text-[13px]">{{ font.designer }}</dd>
            </div>
            <div v-if="font.manufacturer">
              <SectionLabel as="dt">{{ t("fontDetail.foundry") }}</SectionLabel>
              <dd class="mt-1 text-[13px]">{{ font.manufacturer }}</dd>
            </div>
            <div v-if="font.version">
              <SectionLabel as="dt">{{ t("fontDetail.version") }}</SectionLabel>
              <dd class="mt-1 text-[13px]">{{ font.version }}</dd>
            </div>
            <div v-if="font.license">
              <SectionLabel as="dt">{{ t("fontDetail.license") }}</SectionLabel>
              <dd class="mt-1 text-[13px]">
                <a
                  v-if="isSafeUrl(font.licenseUrl)"
                  :href="font.licenseUrl!"
                  target="_blank"
                  rel="noopener"
                  class="underline underline-offset-2 hover:text-foreground"
                >
                  {{ font.license }}
                </a>
                <span v-else>{{ font.license }}</span>
              </dd>
            </div>
            <div>
              <SectionLabel as="dt">{{ t("fontDetail.format") }}</SectionLabel>
              <dd class="mt-1 text-[13px]">
                {{ font.fileFormat.toUpperCase() }}
              </dd>
            </div>
            <div>
              <SectionLabel as="dt">{{ t("fontDetail.size") }}</SectionLabel>
              <dd class="mt-1 text-[13px]">
                {{ formatFileSize(font.fileSize) }}
              </dd>
            </div>
            <div>
              <SectionLabel as="dt">{{ t("fontDetail.hash") }}</SectionLabel>
              <dd class="mt-1 font-mono text-[12px] text-muted-foreground">
                {{ font.fileHash.slice(0, 12) }}&hellip;
              </dd>
            </div>
            <div v-if="font.weightClass">
              <SectionLabel as="dt">{{ t("fontDetail.weight") }}</SectionLabel>
              <dd class="mt-1 text-[13px]">
                {{ font.weightClass }}
                <span
                  v-if="WEIGHT_LABELS[font.weightClass]"
                  class="text-foreground-subtle"
                >
                  · {{ WEIGHT_LABELS[font.weightClass] }}
                </span>
              </dd>
            </div>
            <div v-if="font.widthClass">
              <SectionLabel as="dt">{{ t("fontDetail.width") }}</SectionLabel>
              <dd class="mt-1 text-[13px]">{{ font.widthClass }}</dd>
            </div>
            <div v-if="font.isItalic || font.isOblique">
              <SectionLabel as="dt">{{ t("fontDetail.style") }}</SectionLabel>
              <dd class="mt-1 text-[13px]">
                {{ font.isItalic ? t("fontDetail.italic") : "" }}
                {{ font.isOblique ? t("fontDetail.oblique") : "" }}
              </dd>
            </div>
            <div v-if="font.glyphCount">
              <SectionLabel as="dt">{{ t("fontDetail.glyphs") }}</SectionLabel>
              <dd class="mt-1 text-[13px]">{{ font.glyphCount }}</dd>
            </div>
            <div v-if="font.description" class="sm:col-span-2">
              <SectionLabel as="dt">{{
                t("fontDetail.description")
              }}</SectionLabel>
              <dd class="mt-1 text-[13px] leading-relaxed">
                {{ font.description }}
              </dd>
            </div>
          </dl>
        </Panel>
      </section>

      <!-- Import info -->
      <section>
        <SectionLabel class="mb-3">{{ t("fontDetail.import") }}</SectionLabel>
        <Panel class="p-6">
          <dl class="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
            <div>
              <SectionLabel as="dt">{{
                t("fontDetail.importDate")
              }}</SectionLabel>
              <dd class="mt-1 flex items-center gap-1.5 text-[13px]">
                <Calendar class="size-3.5 text-foreground-subtle" />
                {{ formatDate(font.createdAt) }}
              </dd>
            </div>
            <div>
              <SectionLabel as="dt">{{ t("fontDetail.source") }}</SectionLabel>
              <dd class="mt-1 flex items-center gap-1.5 text-[13px]">
                <Upload class="size-3.5 text-foreground-subtle" />
                {{ sourceLabel(font.source) }}
              </dd>
            </div>
            <div v-if="font.sourceDeviceName">
              <SectionLabel as="dt">{{
                t("fontDetail.importedFrom")
              }}</SectionLabel>
              <dd class="mt-1 flex items-center gap-1.5 text-[13px]">
                <Monitor class="size-3.5 text-foreground-subtle" />
                {{ font.sourceDeviceName }}
              </dd>
            </div>
          </dl>
        </Panel>
      </section>

      <!-- Scripts / Languages -->
      <section v-if="font.supportedScripts?.length">
        <SectionLabel class="mb-3">{{
          t("fontDetail.languages")
        }}</SectionLabel>
        <div class="flex flex-wrap gap-1.5">
          <span
            v-for="script in font.supportedScripts"
            :key="script"
            class="rounded bg-muted px-1.5 py-0.5 font-mono text-[9px] capitalize text-foreground-subtle"
          >
            {{ script }}
          </span>
        </div>
      </section>

      <!-- Glyphs -->
      <section>
        <div class="mb-3 flex items-center justify-between">
          <SectionLabel>{{ t("fontDetail.glyphs") }}</SectionLabel>
          <div v-if="totalGlyphPages > 1" class="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon-sm"
              :disabled="glyphPage === 0"
              @click="glyphPage--"
            >
              <ChevronLeft class="h-4 w-4" />
            </Button>
            <span class="font-mono text-[10px] text-foreground-subtle">
              {{ glyphPage + 1 }} / {{ totalGlyphPages }}
            </span>
            <Button
              variant="outline"
              size="icon-sm"
              :disabled="glyphPage >= totalGlyphPages - 1"
              @click="glyphPage++"
            >
              <ChevronRight class="h-4 w-4" />
            </Button>
          </div>
        </div>
        <Panel class="p-4">
          <div
            class="grid grid-cols-8 gap-1 sm:grid-cols-10 md:grid-cols-12"
            :style="{
              fontFamily: fontLoaded
                ? `'${fontFamily}', monospace`
                : 'monospace',
            }"
          >
            <div
              v-for="(char, i) in currentGlyphs"
              :key="`${glyphPage}-${i}`"
              class="flex h-10 cursor-default select-none items-center justify-center rounded border border-transparent text-lg transition-colors hover:border-separator hover:bg-muted"
            >
              {{ char }}
            </div>
          </div>
        </Panel>
      </section>
    </div>
  </div>
</template>
