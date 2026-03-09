<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from "vue";
import { ChevronRight, RotateCcw } from "lucide-vue-next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import FontStyleRow from "./FontStyleRow.vue";
import type { FontFamily, FamilyMember } from "@/types/api";

const props = defineProps<{
  family: FontFamily;
  previewText: string;
  observe: (el: Element, fontId: string) => void;
  unobserve: (el: Element) => void;
  getFontFamily: (fontId: string) => string;
}>();

const open = ref(false);
const members = ref<FamilyMember[]>([]);
const loadingMembers = ref(false);
const loaded = ref(false);
const fetchError = ref(false);

let abortController: AbortController | null = null;

const CLASSIFICATION_LABELS: Record<string, string> = {
  serif: "Serif",
  "sans-serif": "Sans-serif",
  monospace: "Mono",
  display: "Display",
  handwriting: "Manuscrite",
  symbol: "Symbole",
};

async function fetchMembers() {
  if (loaded.value || loadingMembers.value) return;
  abortController?.abort();
  abortController = new AbortController();

  loadingMembers.value = true;
  fetchError.value = false;
  try {
    const res = await fetch(`/api/font-families/${props.family.id}`, {
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

watch(open, (isOpen) => {
  if (isOpen && !loaded.value) {
    fetchMembers();
  }
});

onBeforeUnmount(() => {
  abortController?.abort();
});
</script>

<template>
  <Collapsible v-model:open="open" class="border-b last:border-b-0">
    <CollapsibleTrigger
      class="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/50"
    >
      <ChevronRight
        class="h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200"
        :class="{ 'rotate-90': open }"
      />
      <span class="font-semibold tracking-tight truncate">
        {{ family.name }}
      </span>
      <span class="text-sm text-muted-foreground">
        {{ family.styleCount }} style{{ family.styleCount !== 1 ? "s" : "" }}
      </span>
      <Badge
        v-if="family.classification"
        variant="secondary"
        class="ml-auto shrink-0"
      >
        {{
          CLASSIFICATION_LABELS[family.classification] ?? family.classification
        }}
      </Badge>
    </CollapsibleTrigger>

    <CollapsibleContent>
      <!-- Loading skeleton -->
      <div
        v-if="loadingMembers && members.length === 0"
        class="space-y-1 pb-2 pl-7"
      >
        <Skeleton
          v-for="i in Math.min(family.styleCount, 4)"
          :key="i"
          class="mx-4 h-10"
        />
      </div>

      <!-- Error state -->
      <div
        v-else-if="fetchError"
        class="flex items-center gap-2 px-4 py-3 pl-11"
      >
        <span class="text-sm text-muted-foreground">Erreur de chargement</span>
        <Button variant="ghost" size="icon-sm" @click="retry">
          <RotateCcw class="h-3.5 w-3.5" />
        </Button>
      </div>

      <!-- Members list -->
      <div v-else class="pb-2 pl-7">
        <FontStyleRow
          v-for="member in members"
          :key="member.fontId"
          :member="member"
          :preview-text="previewText"
          :observe="observe"
          :unobserve="unobserve"
          :get-font-family="getFontFamily"
        />
      </div>
    </CollapsibleContent>
  </Collapsible>
</template>
