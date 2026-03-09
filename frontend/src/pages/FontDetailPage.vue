<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { RouterLink } from "vue-router";
import {
  ArrowLeft,
  Download,
  ChevronLeft,
  ChevronRight,
  Monitor,
  Upload,
  Calendar,
  Loader2,
} from "lucide-vue-next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import type { Font } from "@/types/api";

interface DeviceStatus {
  deviceId: string;
  deviceName: string;
  hostname: string;
  isOnline: boolean;
  installed: boolean;
  activated: boolean;
  localPath: string | null;
  installedAt: string | null;
}

const props = defineProps<{ id: string }>();

const font = ref<Font | null>(null);
const loading = ref(true);
const deviceStatuses = ref<DeviceStatus[]>([]);
const devicesLoading = ref(false);
const actionInProgress = ref<Set<string>>(new Set());
const error = ref<string | null>(null);
const fontLoaded = ref(false);
const previewText = ref("Portez ce vieux whisky au juge blond qui fume");
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

const CLASSIFICATION_LABELS: Record<string, string> = {
  serif: "Serif",
  "sans-serif": "Sans-serif",
  monospace: "Monospace",
  display: "Display",
  handwriting: "Manuscrite",
  symbol: "Symbole",
};

async function fetchFont() {
  fetchAbort?.abort();
  fetchAbort = new AbortController();
  loading.value = true;
  error.value = null;
  try {
    const res = await fetch(`/api/fonts/${props.id}`, {
      signal: fetchAbort.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    font.value = await res.json();
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") return;
    error.value = e instanceof Error ? e.message : "Erreur inconnue";
  } finally {
    loading.value = false;
  }
}

async function loadFontFace() {
  try {
    fontFace = new FontFace(
      fontFamily.value,
      `url(/api/fonts/${props.id}/preview)`,
      { display: "swap" },
    );
    await fontFace.load();
    document.fonts.add(fontFace);
    fontLoaded.value = true;
  } catch {
    fontFace = null;
  }
}

function handleDownload() {
  if (!font.value) return;
  const a = document.createElement("a");
  a.href = `/api/fonts/${props.id}/file`;
  a.download = font.value.originalFilename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
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

const SOURCE_LABELS: Record<string, string> = {
  upload: "Upload web",
  local_scan: "Agent (scan local)",
  google_fonts: "Google Fonts",
};

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function fetchDeviceStatuses() {
  devicesLoading.value = true;
  try {
    const res = await fetch(`/api/fonts/${props.id}/devices`);
    if (res.ok) {
      deviceStatuses.value = await res.json();
    }
  } catch (e) {
    console.error("Failed to fetch device statuses:", e);
  } finally {
    devicesLoading.value = false;
  }
}

async function handleInstall(deviceId: string) {
  actionInProgress.value = new Set([...actionInProgress.value, deviceId]);
  try {
    const res = await fetch(`/api/fonts/${props.id}/install/${deviceId}`, {
      method: "POST",
    });
    if (res.ok) {
      // Mise à jour optimiste
      const status = deviceStatuses.value.find((s) => s.deviceId === deviceId);
      if (status) {
        status.installed = true;
        status.activated = true;
      }
      // Rafraîchir le statut après un court délai (laisser le temps à l'agent)
      setTimeout(() => fetchDeviceStatuses(), 2000);
    }
  } catch (e) {
    console.error("Install error:", e);
  } finally {
    const next = new Set(actionInProgress.value);
    next.delete(deviceId);
    actionInProgress.value = next;
  }
}

async function handleUninstall(deviceId: string) {
  actionInProgress.value = new Set([...actionInProgress.value, deviceId]);
  try {
    const res = await fetch(`/api/fonts/${props.id}/uninstall/${deviceId}`, {
      method: "POST",
    });
    if (res.ok) {
      // Mettre à jour immédiatement côté frontend
      const status = deviceStatuses.value.find((s) => s.deviceId === deviceId);
      if (status) {
        status.installed = false;
        status.activated = false;
        status.localPath = null;
        status.installedAt = null;
      }
    }
  } catch (e) {
    console.error("Uninstall error:", e);
  } finally {
    const next = new Set(actionInProgress.value);
    next.delete(deviceId);
    actionInProgress.value = next;
  }
}

const activationInProgress = ref<Set<string>>(new Set());

function isSystemFont(localPath: string | null): boolean {
  if (!localPath) return false;
  return localPath.startsWith("/Library/Fonts") || localPath.startsWith("/System/Library/Fonts");
}

async function handleActivate(deviceId: string) {
  activationInProgress.value = new Set([...activationInProgress.value, deviceId]);
  try {
    const res = await fetch(`/api/fonts/${props.id}/activate/${deviceId}`, {
      method: "POST",
    });
    if (res.ok) {
      setTimeout(() => fetchDeviceStatuses(), 2000);
    }
  } catch (e) {
    console.error("Activate error:", e);
  } finally {
    const next = new Set(activationInProgress.value);
    next.delete(deviceId);
    activationInProgress.value = next;
  }
}

async function handleDeactivate(deviceId: string) {
  activationInProgress.value = new Set([...activationInProgress.value, deviceId]);
  try {
    const res = await fetch(`/api/fonts/${props.id}/deactivate/${deviceId}`, {
      method: "POST",
    });
    if (res.ok) {
      const status = deviceStatuses.value.find((s) => s.deviceId === deviceId);
      if (status) {
        status.activated = false;
      }
    }
  } catch (e) {
    console.error("Deactivate error:", e);
  } finally {
    const next = new Set(activationInProgress.value);
    next.delete(deviceId);
    activationInProgress.value = next;
  }
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
  <!-- Loading -->
  <div v-if="loading" class="mx-auto max-w-4xl space-y-8">
    <Skeleton class="h-8 w-64" />
    <Skeleton class="h-5 w-40" />
    <Skeleton class="h-24 w-full" />
    <div class="space-y-3">
      <Skeleton v-for="i in 5" :key="i" class="h-6 w-full" />
    </div>
  </div>

  <!-- Error -->
  <div v-else-if="error" class="mx-auto max-w-4xl">
    <div class="rounded-xl border border-dashed p-12 text-center">
      <p class="text-muted-foreground">Impossible de charger la police.</p>
      <p class="text-sm text-muted-foreground mt-1">{{ error }}</p>
      <div class="mt-4 flex justify-center gap-3">
        <Button variant="outline" as-child>
          <RouterLink :to="{ name: 'fonts' }">
            <ArrowLeft class="mr-2 h-4 w-4" />
            Retour
          </RouterLink>
        </Button>
        <Button @click="fetchFont">Réessayer</Button>
      </div>
    </div>
  </div>

  <!-- Content -->
  <div v-else-if="font" class="mx-auto max-w-4xl space-y-8">
    <!-- Header -->
    <div>
      <RouterLink
        :to="{ name: 'fonts' }"
        class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground mb-4"
      >
        <ArrowLeft class="mr-1 h-4 w-4" />
        Polices
      </RouterLink>

      <div class="flex items-start justify-between gap-4">
        <div>
          <h1 class="text-3xl font-bold tracking-tight">
            {{ font.familyName ?? font.originalFilename }}
          </h1>
          <div class="flex items-center gap-2 mt-1">
            <span class="text-muted-foreground">
              {{ font.subfamilyName ?? font.fileFormat.toUpperCase() }}
            </span>
            <Badge v-if="font.classification" variant="secondary">
              {{
                CLASSIFICATION_LABELS[font.classification] ??
                font.classification
              }}
            </Badge>
            <Badge v-if="font.isVariable" variant="outline">Variable</Badge>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <Sheet>
            <SheetTrigger as-child>
              <Button variant="outline" @click="fetchDeviceStatuses">
                <Monitor class="mr-2 h-4 w-4" />
                Appareils
              </Button>
            </SheetTrigger>
            <SheetContent>
              <SheetHeader>
                <SheetTitle>Installation par appareil</SheetTitle>
                <SheetDescription>
                  Gérez l'installation de cette police sur chaque machine connectée.
                </SheetDescription>
              </SheetHeader>

              <div class="mt-6 space-y-4">
                <!-- Loading -->
                <div v-if="devicesLoading" class="space-y-4">
                  <Skeleton v-for="i in 2" :key="i" class="h-28 w-full rounded-lg" />
                </div>

                <!-- Empty -->
                <p
                  v-else-if="deviceStatuses.length === 0"
                  class="text-sm text-muted-foreground text-center py-8"
                >
                  Aucun appareil enregistré.
                </p>

                <!-- Device list -->
                <template v-else>
                  <div
                    v-for="status in deviceStatuses"
                    :key="status.deviceId"
                    class="rounded-lg border p-4 space-y-4"
                  >
                    <!-- Device header -->
                    <div class="flex items-center gap-2">
                      <span
                        class="h-2 w-2 shrink-0 rounded-full"
                        :class="status.isOnline ? 'bg-green-500' : 'bg-muted-foreground/40'"
                      />
                      <span class="text-sm font-medium truncate">{{ status.deviceName }}</span>
                      <span v-if="!status.isOnline" class="text-xs text-muted-foreground ml-auto">Hors ligne</span>
                    </div>

                    <!-- Install toggle -->
                    <div class="flex items-center justify-between gap-3">
                      <div class="space-y-0.5">
                        <Label class="text-sm">Installer la police</Label>
                        <p class="text-xs text-muted-foreground">
                          {{ status.installed ? 'Fichier présent sur l\'appareil' : 'Non installée' }}
                        </p>
                      </div>
                      <div class="flex items-center gap-2">
                        <Loader2
                          v-if="actionInProgress.has(status.deviceId)"
                          class="h-4 w-4 animate-spin text-muted-foreground"
                        />
                        <Switch
                          :model-value="status.installed"
                          :disabled="!status.isOnline || actionInProgress.has(status.deviceId)"
                          @update:model-value="status.installed ? handleUninstall(status.deviceId) : handleInstall(status.deviceId)"
                        />
                      </div>
                    </div>

                    <!-- Activate toggle -->
                    <div class="flex items-center justify-between gap-3">
                      <div class="space-y-0.5">
                        <Label class="text-sm" :class="!status.installed && 'text-muted-foreground'">Activer sur le système</Label>
                        <p class="text-xs text-muted-foreground">
                          <template v-if="!status.installed">Installez d'abord la police</template>
                          <template v-else-if="isSystemFont(status.localPath)">Police système (non modifiable)</template>
                          <template v-else-if="status.activated">Disponible dans les applications</template>
                          <template v-else>Désactivée — invisible pour les applications</template>
                        </p>
                      </div>
                      <div class="flex items-center gap-2">
                        <Loader2
                          v-if="activationInProgress.has(status.deviceId)"
                          class="h-4 w-4 animate-spin text-muted-foreground"
                        />
                        <Switch
                          :model-value="status.activated"
                          :disabled="!status.installed || !status.isOnline || isSystemFont(status.localPath) || activationInProgress.has(status.deviceId)"
                          @update:model-value="status.activated ? handleDeactivate(status.deviceId) : handleActivate(status.deviceId)"
                        />
                      </div>
                    </div>

                    <p v-if="status.installed && status.installedAt" class="text-xs text-muted-foreground">
                      Installée le {{ formatDate(status.installedAt) }}
                    </p>
                  </div>
                </template>
              </div>
            </SheetContent>
          </Sheet>

          <Button @click="handleDownload">
            <Download class="mr-2 h-4 w-4" />
            Télécharger
          </Button>
        </div>
      </div>
    </div>

    <Separator />

    <!-- Preview -->
    <section>
      <h2 class="text-lg font-semibold mb-3">Aperçu</h2>
      <Input
        v-model="previewText"
        placeholder="Saisissez un texte..."
        class="mb-4"
      />
      <div
        class="rounded-xl border bg-card p-6 text-2xl leading-relaxed break-words"
        :style="{
          fontFamily: fontLoaded
            ? `'${fontFamily}', sans-serif`
            : 'sans-serif',
        }"
      >
        {{ previewText }}
      </div>
    </section>

    <!-- Waterfall -->
    <section>
      <h2 class="text-lg font-semibold mb-3">Cascade</h2>
      <div class="rounded-xl border bg-card p-6 space-y-4">
        <div
          v-for="size in WATERFALL_SIZES"
          :key="size"
          class="flex items-baseline gap-4"
        >
          <span class="w-10 shrink-0 text-right text-xs text-muted-foreground">
            {{ size }}px
          </span>
          <span
            class="break-words min-w-0"
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
      </div>
    </section>

    <Separator />

    <!-- Metadata -->
    <section>
      <h2 class="text-lg font-semibold mb-3">Métadonnées</h2>
      <div class="rounded-xl border bg-card p-6">
        <dl class="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3">
          <div v-if="font.designer">
            <dt class="text-sm text-muted-foreground">Designer</dt>
            <dd class="text-sm font-medium">{{ font.designer }}</dd>
          </div>
          <div v-if="font.manufacturer">
            <dt class="text-sm text-muted-foreground">Fonderie</dt>
            <dd class="text-sm font-medium">{{ font.manufacturer }}</dd>
          </div>
          <div v-if="font.version">
            <dt class="text-sm text-muted-foreground">Version</dt>
            <dd class="text-sm font-medium">{{ font.version }}</dd>
          </div>
          <div v-if="font.license">
            <dt class="text-sm text-muted-foreground">Licence</dt>
            <dd class="text-sm font-medium">
              <a
                v-if="isSafeUrl(font.licenseUrl)"
                :href="font.licenseUrl!"
                target="_blank"
                rel="noopener"
                class="underline hover:text-foreground"
              >
                {{ font.license }}
              </a>
              <span v-else>{{ font.license }}</span>
            </dd>
          </div>
          <div>
            <dt class="text-sm text-muted-foreground">Format</dt>
            <dd class="text-sm font-medium">
              {{ font.fileFormat.toUpperCase() }}
            </dd>
          </div>
          <div>
            <dt class="text-sm text-muted-foreground">Taille</dt>
            <dd class="text-sm font-medium">
              {{ formatFileSize(font.fileSize) }}
            </dd>
          </div>
          <div>
            <dt class="text-sm text-muted-foreground">Hash</dt>
            <dd class="text-sm font-medium font-mono">
              {{ font.fileHash.slice(0, 12) }}&hellip;
            </dd>
          </div>
          <div v-if="font.weightClass">
            <dt class="text-sm text-muted-foreground">Graisse</dt>
            <dd class="text-sm font-medium">
              {{ font.weightClass }}
              <span
                v-if="WEIGHT_LABELS[font.weightClass]"
                class="text-muted-foreground"
              >
                ({{ WEIGHT_LABELS[font.weightClass] }})
              </span>
            </dd>
          </div>
          <div v-if="font.widthClass">
            <dt class="text-sm text-muted-foreground">Largeur</dt>
            <dd class="text-sm font-medium">{{ font.widthClass }}</dd>
          </div>
          <div v-if="font.isItalic || font.isOblique">
            <dt class="text-sm text-muted-foreground">Style</dt>
            <dd class="text-sm font-medium">
              {{ font.isItalic ? "Italique" : "" }}
              {{ font.isOblique ? "Oblique" : "" }}
            </dd>
          </div>
          <div v-if="font.glyphCount">
            <dt class="text-sm text-muted-foreground">Glyphes</dt>
            <dd class="text-sm font-medium">{{ font.glyphCount }}</dd>
          </div>
          <div v-if="font.description">
            <dt class="text-sm text-muted-foreground">Description</dt>
            <dd class="text-sm font-medium sm:col-span-2">
              {{ font.description }}
            </dd>
          </div>
        </dl>
      </div>
    </section>

    <!-- Import info -->
    <section>
      <h2 class="text-lg font-semibold mb-3">Import</h2>
      <div class="rounded-xl border bg-card p-6">
        <dl class="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3">
          <div>
            <dt class="text-sm text-muted-foreground">Date d'import</dt>
            <dd class="text-sm font-medium flex items-center gap-1.5">
              <Calendar class="h-3.5 w-3.5 text-muted-foreground" />
              {{ formatDate(font.createdAt) }}
            </dd>
          </div>
          <div>
            <dt class="text-sm text-muted-foreground">Source</dt>
            <dd class="text-sm font-medium flex items-center gap-1.5">
              <Upload class="h-3.5 w-3.5 text-muted-foreground" />
              {{ SOURCE_LABELS[font.source] ?? font.source }}
            </dd>
          </div>
          <div v-if="font.sourceDeviceName">
            <dt class="text-sm text-muted-foreground">Importée depuis</dt>
            <dd class="text-sm font-medium flex items-center gap-1.5">
              <Monitor class="h-3.5 w-3.5 text-muted-foreground" />
              {{ font.sourceDeviceName }}
            </dd>
          </div>
        </dl>
      </div>
    </section>

    <!-- Scripts / Languages -->
    <section v-if="font.supportedScripts?.length">
      <h2 class="text-lg font-semibold mb-3">Langues</h2>
      <div class="flex flex-wrap gap-2">
        <Badge
          v-for="script in font.supportedScripts"
          :key="script"
          variant="secondary"
          class="capitalize"
        >
          {{ script }}
        </Badge>
      </div>
    </section>

    <!-- Glyphs -->
    <section>
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold">Glyphes</h2>
        <div v-if="totalGlyphPages > 1" class="flex items-center gap-2">
          <Button
            variant="outline"
            size="icon-sm"
            :disabled="glyphPage === 0"
            @click="glyphPage--"
          >
            <ChevronLeft class="h-4 w-4" />
          </Button>
          <span class="text-sm text-muted-foreground">
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
      <div
        class="grid grid-cols-8 sm:grid-cols-10 md:grid-cols-12 gap-1"
        :style="{
          fontFamily: fontLoaded
            ? `'${fontFamily}', monospace`
            : 'monospace',
        }"
      >
        <div
          v-for="(char, i) in currentGlyphs"
          :key="`${glyphPage}-${i}`"
          class="flex items-center justify-center h-10 text-lg rounded border border-transparent hover:border-border hover:bg-accent cursor-default select-none"
        >
          {{ char }}
        </div>
      </div>
    </section>
  </div>
</template>
