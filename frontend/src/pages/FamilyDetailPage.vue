<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { ArrowLeft, Download, Trash2, Plus } from "lucide-vue-next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import MergeOrphanDialog from "@/components/families/MergeOrphanDialog.vue";
import type { FontFamilyDetail } from "@/types/api";

const props = defineProps<{ id: string }>();
const router = useRouter();

const family = ref<FontFamilyDetail | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const previewText = ref("Portez ce vieux whisky au juge blond qui fume");
const removing = ref<string | null>(null);
const deleting = ref(false);
const memberFonts = ref<Map<string, boolean>>(new Map());

const loadedFaces: Map<string, FontFace> = new Map();
let fetchAbort: AbortController | null = null;

function getMemberFontFamily(fontId: string): string {
  return `family-member-${fontId}`;
}

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

async function fetchFamily() {
  fetchAbort?.abort();
  fetchAbort = new AbortController();
  loading.value = true;
  error.value = null;
  try {
    const res = await fetch(`/api/font-families/${props.id}`, {
      signal: fetchAbort.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    family.value = await res.json();
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") return;
    error.value = e instanceof Error ? e.message : "Erreur inconnue";
  } finally {
    loading.value = false;
  }
}

function unloadAllFaces() {
  for (const face of loadedFaces.values()) {
    document.fonts.delete(face);
  }
  loadedFaces.clear();
  memberFonts.value = new Map();
}

async function loadMemberFonts() {
  if (!family.value?.members.length) return;
  unloadAllFaces();
  for (const member of family.value.members) {
    const familyName = getMemberFontFamily(member.fontId);
    try {
      const face = new FontFace(
        familyName,
        `url(/api/fonts/${member.fontId}/preview)`,
        { display: "swap" },
      );
      await face.load();
      document.fonts.add(face);
      loadedFaces.set(member.fontId, face);
      memberFonts.value.set(member.fontId, true);
    } catch {
      // Font failed to load — card will show fallback
    }
  }
}

async function removeMember(fontId: string) {
  removing.value = fontId;
  try {
    const res = await fetch(`/api/font-families/${props.id}/fonts/${fontId}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await fetchFamily();
    if (family.value) loadMemberFonts();
  } catch {
    // Remove failed silently
  } finally {
    removing.value = null;
  }
}

async function deleteFamily() {
  deleting.value = true;
  try {
    const res = await fetch(`/api/font-families/${props.id}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    router.push({ name: "families" });
  } catch {
    // Delete failed silently
  } finally {
    deleting.value = false;
  }
}

function handleDownload(fontId: string, filename: string) {
  const a = document.createElement("a");
  a.href = `/api/fonts/${fontId}/file`;
  a.download = filename;
  a.click();
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

onMounted(async () => {
  await fetchFamily();
  if (family.value) loadMemberFonts();
});

onUnmounted(() => {
  fetchAbort?.abort();
  unloadAllFaces();
});
</script>

<template>
  <!-- Loading -->
  <div v-if="loading" class="mx-auto max-w-5xl space-y-8 p-6">
    <Skeleton class="h-8 w-64" />
    <Skeleton class="h-5 w-40" />
    <Skeleton class="h-24 w-full" />
    <div class="grid gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
      <Skeleton v-for="i in 4" :key="i" class="h-32 w-full rounded-xl" />
    </div>
  </div>

  <!-- Error -->
  <div v-else-if="error" class="mx-auto max-w-5xl p-6">
    <div class="rounded-xl border border-dashed p-12 text-center">
      <p class="text-muted-foreground">Impossible de charger la famille.</p>
      <p class="text-sm text-muted-foreground mt-1">{{ error }}</p>
      <div class="mt-4 flex justify-center gap-3">
        <Button variant="outline" as-child>
          <RouterLink :to="{ name: 'families' }">
            <ArrowLeft class="mr-2 h-4 w-4" />
            Retour
          </RouterLink>
        </Button>
        <Button @click="fetchFamily">Reessayer</Button>
      </div>
    </div>
  </div>

  <!-- Content -->
  <div v-else-if="family" class="mx-auto max-w-5xl space-y-8 p-6">
    <!-- Header -->
    <div>
      <RouterLink
        :to="{ name: 'families' }"
        class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground mb-4"
      >
        <ArrowLeft class="mr-1 h-4 w-4" />
        Familles
      </RouterLink>

      <div class="flex items-start justify-between gap-4">
        <div>
          <h1 class="text-3xl font-bold tracking-tight">
            {{ family.name }}
          </h1>
          <div class="flex items-center gap-2 mt-1">
            <span class="text-muted-foreground">
              {{ family.styleCount }} style{{
                family.styleCount !== 1 ? "s" : ""
              }}
            </span>
            <Badge v-if="family.classification" variant="secondary">
              {{
                CLASSIFICATION_LABELS[family.classification] ??
                family.classification
              }}
            </Badge>
            <Badge v-if="family.isAutoGrouped" variant="outline">Auto</Badge>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <MergeOrphanDialog
            :family-id="family.id"
            :family-name="family.name"
            @merged="fetchFamily().then(() => family && loadMemberFonts())"
          >
            <template #trigger="{ open }">
              <Button variant="outline" size="sm" @click="open">
                <Plus class="mr-1.5 h-3.5 w-3.5" />
                Ajouter des polices
              </Button>
            </template>
          </MergeOrphanDialog>
          <Button
            variant="outline"
            size="sm"
            :disabled="deleting"
            class="text-destructive hover:text-destructive"
            @click="deleteFamily"
          >
            <Trash2 class="mr-1.5 h-3.5 w-3.5" />
            Supprimer
          </Button>
        </div>
      </div>
    </div>

    <!-- Metadata -->
    <div v-if="family.designer || family.manufacturer" class="flex gap-6">
      <div v-if="family.designer">
        <span class="text-sm text-muted-foreground">Designer</span>
        <p class="text-sm font-medium">{{ family.designer }}</p>
      </div>
      <div v-if="family.manufacturer">
        <span class="text-sm text-muted-foreground">Fonderie</span>
        <p class="text-sm font-medium">{{ family.manufacturer }}</p>
      </div>
    </div>

    <Separator />

    <!-- Preview -->
    <section>
      <h2 class="text-lg font-semibold mb-3">Apercu</h2>
      <Input
        v-model="previewText"
        placeholder="Saisissez un texte..."
        class="mb-4"
      />
      <div
        v-if="family.members.length > 0"
        class="rounded-xl border bg-card p-6 text-2xl leading-relaxed break-words"
        :style="{
          fontFamily: family.members[0] && memberFonts.has(family.members[0].fontId)
            ? `'${getMemberFontFamily(family.members[0].fontId)}', sans-serif`
            : 'sans-serif',
        }"
      >
        {{ previewText }}
      </div>
    </section>

    <Separator />

    <!-- Members grid -->
    <section>
      <h2 class="text-lg font-semibold mb-3">
        Styles ({{ family.members.length }})
      </h2>

      <div
        v-if="family.members.length === 0"
        class="rounded-xl border border-dashed p-8 text-center"
      >
        <p class="text-muted-foreground">Aucun style dans cette famille.</p>
      </div>

      <div
        v-else
        class="grid gap-3 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4"
      >
        <div
          v-for="member in family.members"
          :key="member.fontId"
          class="group relative flex flex-col rounded-xl border bg-card p-4 transition-colors hover:border-foreground/20"
        >
          <!-- Preview -->
          <div
            class="mb-3 h-10 overflow-hidden text-lg leading-relaxed text-foreground/90"
            :style="{
              fontFamily: memberFonts.has(member.fontId)
                ? `'${getMemberFontFamily(member.fontId)}', sans-serif`
                : 'sans-serif',
            }"
          >
            {{ previewText }}
          </div>

          <!-- Name & weight -->
          <RouterLink
            :to="{ name: 'font-detail', params: { id: member.fontId } }"
            class="font-medium text-sm hover:underline truncate"
          >
            {{
              member.subfamilyName ?? member.fullName ?? member.originalFilename
            }}
          </RouterLink>
          <div class="flex items-center gap-1.5 mt-1">
            <Badge
              v-if="member.weightClass"
              variant="outline"
              class="text-[10px]"
            >
              {{ WEIGHT_LABELS[member.weightClass] ?? member.weightClass }}
            </Badge>
            <Badge v-if="member.isItalic" variant="outline" class="text-[10px]">
              Italique
            </Badge>
            <Badge
              v-if="member.isVariable"
              variant="outline"
              class="text-[10px]"
            >
              Variable
            </Badge>
          </div>

          <!-- Footer -->
          <div class="mt-auto flex items-center justify-between pt-3">
            <span class="text-xs text-muted-foreground">
              {{ member.fileFormat.toUpperCase() }} ·
              {{ formatFileSize(member.fileSize) }}
            </span>
            <div
              class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <Button
                variant="ghost"
                size="icon-sm"
                @click="handleDownload(member.fontId, member.originalFilename)"
              >
                <Download class="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                class="text-destructive hover:text-destructive"
                :disabled="removing === member.fontId"
                @click="removeMember(member.fontId)"
              >
                <Trash2 class="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
