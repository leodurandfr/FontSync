<script setup lang="ts">
import { ref } from "vue";
import { Upload, Loader2, CheckCircle2, AlertCircle } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useFontsStore } from "@/stores/fonts";
import { useFamiliesStore } from "@/stores/families";
import { useFamilyFiltersStore } from "@/stores/familyFilters";
import type { FontUploadResponse } from "@/types/api";

const ACCEPT = ".ttf,.otf,.ttc,.woff,.woff2";
const ACCEPTED_EXTENSIONS = ACCEPT.split(",");

function hasFontExtension(name: string): boolean {
  const lower = name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

const { t } = useI18n();

const fontsStore = useFontsStore();
const familiesStore = useFamiliesStore();
const filtersStore = useFamilyFiltersStore();

const open = ref(false);
const dragOver = ref(false);
const uploading = ref(false);
const error = ref<string | null>(null);
const result = ref<FontUploadResponse | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

function reset() {
  uploading.value = false;
  error.value = null;
  result.value = null;
  dragOver.value = false;
}

function onOpenChange(value: boolean) {
  open.value = value;
  if (!value) reset();
}

async function upload(files: File[]) {
  if (files.length === 0 || uploading.value) return;
  uploading.value = true;
  error.value = null;
  result.value = null;
  try {
    result.value = await fontsStore.uploadFonts(files);
    // Le regroupement en familles est fait côté serveur : on recharge la liste.
    if (result.value.imported.length > 0) {
      await familiesStore.fetchFamilies(filtersStore.toFilters());
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : t("common.unknownError");
  } finally {
    uploading.value = false;
  }
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  upload(Array.from(input.files ?? []));
  input.value = "";
}

// Le drag & drop natif n'expose que les fichiers de premier niveau via
// `dataTransfer.files`. Pour accepter un dossier (voire une arborescence),
// on parcourt récursivement les `FileSystemEntry` exposés par les navigateurs.
type FileSystemEntryLike = {
  isFile: boolean;
  isDirectory: boolean;
  file: (cb: (file: File) => void, err?: (e: unknown) => void) => void;
  createReader: () => {
    readEntries: (
      cb: (entries: FileSystemEntryLike[]) => void,
      err?: (e: unknown) => void,
    ) => void;
  };
};

function readEntryFile(entry: FileSystemEntryLike): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject));
}

function readDirEntries(
  reader: ReturnType<FileSystemEntryLike["createReader"]>,
): Promise<FileSystemEntryLike[]> {
  return new Promise((resolve, reject) =>
    reader.readEntries(resolve, reject),
  );
}

async function collectEntryFiles(entry: FileSystemEntryLike): Promise<File[]> {
  if (entry.isFile) {
    const file = await readEntryFile(entry);
    return hasFontExtension(file.name) ? [file] : [];
  }
  if (entry.isDirectory) {
    const reader = entry.createReader();
    const files: File[] = [];
    // `readEntries` ne renvoie qu'un lot à la fois : on boucle jusqu'à épuisement.
    for (;;) {
      const batch = await readDirEntries(reader);
      if (batch.length === 0) break;
      for (const child of batch) files.push(...(await collectEntryFiles(child)));
    }
    return files;
  }
  return [];
}

async function onDrop(event: DragEvent) {
  dragOver.value = false;
  const items = event.dataTransfer?.items;
  const entries = items
    ? Array.from(items)
        .map((item) =>
          "webkitGetAsEntry" in item
            ? (item.webkitGetAsEntry() as unknown as FileSystemEntryLike | null)
            : null,
        )
        .filter((entry): entry is FileSystemEntryLike => entry !== null)
    : [];

  // Si l'API d'entries est disponible, on l'utilise (gère les dossiers).
  // Sinon, repli sur la liste plate des fichiers.
  if (entries.length > 0) {
    const collected = await Promise.all(entries.map(collectEntryFiles));
    upload(collected.flat());
  } else {
    upload(
      Array.from(event.dataTransfer?.files ?? []).filter((f) =>
        hasFontExtension(f.name),
      ),
    );
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="onOpenChange">
    <DialogTrigger as-child>
      <!-- Trigger par défaut surchargeable : la sidebar fournit son propre bouton. -->
      <slot>
        <Button size="sm" class="shrink-0">
          <Upload class="h-4 w-4 mr-1.5" />
          {{ t("upload.trigger") }}
        </Button>
      </slot>
    </DialogTrigger>
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>{{ t("upload.title") }}</DialogTitle>
        <DialogDescription>
          {{ t("upload.acceptedFormats") }}
        </DialogDescription>
      </DialogHeader>

      <!-- Drop zone -->
      <button
        type="button"
        class="flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-8 text-center transition-colors"
        :class="
          dragOver
            ? 'border-primary bg-accent'
            : 'hover:border-primary/50 hover:bg-accent/50'
        "
        :disabled="uploading"
        @click="fileInput?.click()"
        @dragover.prevent="dragOver = true"
        @dragleave.prevent="dragOver = false"
        @drop.prevent="onDrop"
      >
        <Loader2
          v-if="uploading"
          class="h-6 w-6 animate-spin text-muted-foreground"
        />
        <Upload v-else class="h-6 w-6 text-muted-foreground" />
        <span class="text-sm font-medium">
          {{ uploading ? t("upload.uploading") : t("upload.dropHint") }}
        </span>
      </button>

      <input
        ref="fileInput"
        type="file"
        multiple
        :accept="ACCEPT"
        class="hidden"
        @change="onFileChange"
      />

      <!-- Error -->
      <p v-if="error" class="flex items-center gap-2 text-sm text-destructive">
        <AlertCircle class="h-4 w-4 shrink-0" />
        {{ error }}
      </p>

      <!-- Result summary -->
      <div v-if="result" class="space-y-1.5 text-sm">
        <p
          v-if="result.imported.length > 0"
          class="flex items-center gap-2 text-green-600 dark:text-green-500"
        >
          <CheckCircle2 class="h-4 w-4 shrink-0" />
          {{
            t("upload.imported", result.imported.length, {
              named: { n: result.imported.length },
            })
          }}
        </p>
        <p v-if="result.duplicates.length > 0" class="text-muted-foreground">
          {{
            t("upload.duplicates", result.duplicates.length, {
              named: { n: result.duplicates.length },
            })
          }}
        </p>
        <div v-if="result.errors.length > 0" class="space-y-1">
          <p
            v-for="err in result.errors"
            :key="err.filename"
            class="flex items-start gap-2 text-destructive"
          >
            <AlertCircle class="h-4 w-4 shrink-0 mt-0.5" />
            <span
              ><span class="font-medium">{{ err.filename }}</span> —
              {{ err.detail }}</span
            >
          </p>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
