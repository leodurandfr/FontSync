<script setup lang="ts">
import { ref, watch } from "vue";
import { Loader2, Check } from "lucide-vue-next";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import type { Font } from "@/types/api";

const props = defineProps<{
  familyId: string;
  familyName: string;
}>();

const emit = defineEmits<{
  merged: [];
}>();

const open = ref(false);
const orphanFonts = ref<Font[]>([]);
const selectedFontIds = ref<Set<string>>(new Set());
const loading = ref(false);
const submitting = ref(false);

watch(open, async (isOpen) => {
  if (isOpen) {
    selectedFontIds.value = new Set();
    loading.value = true;
    try {
      const res = await fetch(
        "/api/fonts?orphan=true&per_page=200&sort=family_name&order=asc",
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      orphanFonts.value = data.items;
    } catch {
      orphanFonts.value = [];
    } finally {
      loading.value = false;
    }
  }
});

function toggleFont(fontId: string) {
  const next = new Set(selectedFontIds.value);
  if (next.has(fontId)) {
    next.delete(fontId);
  } else {
    next.add(fontId);
  }
  selectedFontIds.value = next;
}

async function submit() {
  if (selectedFontIds.value.size === 0) return;
  submitting.value = true;
  try {
    const res = await fetch(`/api/font-families/${props.familyId}/fonts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fontIds: [...selectedFontIds.value] }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    open.value = false;
    emit("merged");
  } catch {
    // Submit failed silently
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog v-model:open="open">
    <slot name="trigger" :open="() => (open = true)" />
    <DialogContent class="sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>Ajouter des polices orphelines</DialogTitle>
        <DialogDescription>
          Ajouter des polices sans famille a {{ familyName }}.
        </DialogDescription>
      </DialogHeader>

      <div v-if="loading" class="flex justify-center py-8">
        <Loader2 class="h-5 w-5 animate-spin text-muted-foreground" />
      </div>

      <Command v-else class="rounded-lg border">
        <CommandInput placeholder="Rechercher une police..." />
        <CommandList class="max-h-64">
          <CommandEmpty>Aucune police orpheline.</CommandEmpty>
          <CommandGroup>
            <CommandItem
              v-for="font in orphanFonts"
              :key="font.id"
              :value="font.familyName ?? font.originalFilename"
              class="flex items-center gap-2"
              @select.prevent="toggleFont(font.id)"
            >
              <div
                class="flex h-4 w-4 items-center justify-center rounded border"
                :class="
                  selectedFontIds.has(font.id)
                    ? 'bg-primary border-primary'
                    : ''
                "
              >
                <Check
                  v-if="selectedFontIds.has(font.id)"
                  class="h-3 w-3 text-primary-foreground"
                />
              </div>
              <span class="truncate">{{
                font.familyName ?? font.originalFilename
              }}</span>
              <span
                v-if="font.subfamilyName"
                class="text-muted-foreground text-xs ml-auto"
              >
                {{ font.subfamilyName }}
              </span>
            </CommandItem>
          </CommandGroup>
        </CommandList>
      </Command>

      <DialogFooter>
        <Button variant="outline" @click="open = false">Annuler</Button>
        <Button
          :disabled="selectedFontIds.size === 0 || submitting"
          @click="submit"
        >
          <Loader2 v-if="submitting" class="mr-2 h-4 w-4 animate-spin" />
          Ajouter {{ selectedFontIds.size }} police{{
            selectedFontIds.size > 1 ? "s" : ""
          }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
