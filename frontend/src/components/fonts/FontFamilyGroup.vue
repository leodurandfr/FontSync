<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from "vue";
import { ChevronRight, RotateCcw } from "lucide-vue-next";
import { RouterLink } from "vue-router";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import FontStyleRow from "./FontStyleRow.vue";
import DeviceInstallSheet from "./DeviceInstallSheet.vue";
import type { FontFamily, FamilyMember } from "@/types/api";

const props = defineProps<{
  family: FontFamily;
  previewText: string;
  previewSize: number;
  observe: (el: Element, fontId: string) => void;
  unobserve: (el: Element) => void;
  getFontFamily: (fontId: string) => string;
}>();

const open = ref(false);
const members = ref<FamilyMember[]>([]);
const loadingMembers = ref(false);
const loaded = ref(false);
const fetchError = ref(false);
const wrapperRef = ref<HTMLElement | null>(null);
const headerRef = ref<HTMLElement | null>(null);

let abortController: AbortController | null = null;

const isMultiStyle = props.family.styleCount > 1;

const previewFontId = props.family.previewFont?.id ?? null;

const familyFontIds = computed(() => {
  if (members.value.length > 0) {
    return members.value.map((m) => m.fontId);
  }
  return previewFontId ? [previewFontId] : [];
});

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

function toggle() {
  if (!isMultiStyle) return;
  open.value = !open.value;
}

watch(open, (isOpen) => {
  if (isOpen && !loaded.value) {
    fetchMembers();
  }
});

onMounted(() => {
  if (previewFontId && headerRef.value) {
    props.observe(headerRef.value, previewFontId);
  }
});

onBeforeUnmount(() => {
  abortController?.abort();
  if (headerRef.value) {
    props.unobserve(headerRef.value);
  }
});
</script>

<template>
  <div ref="wrapperRef" class="border-b last:border-b-0">
    <!-- Header row -->
    <div ref="headerRef" class="flex items-center">
      <component
        :is="isMultiStyle ? 'button' : RouterLink"
        v-bind="
          isMultiStyle
            ? { type: 'button' }
            : {
                to: {
                  name: 'font-detail',
                  params: { id: family.previewFont?.id },
                },
              }
        "
        class="flex flex-1 min-w-0 flex-col gap-0.5 px-4 py-3 text-left transition-colors hover:bg-accent/50"
        @click="isMultiStyle ? toggle() : undefined"
      >
        <!-- Line 1: Family name · N styles -->
        <span class="text-sm text-muted-foreground truncate">
          {{ family.name
          }}<template v-if="isMultiStyle">
            &middot; {{ family.styleCount }} styles</template
          >
        </span>

        <!-- Line 2: Chevron + Preview -->
        <div class="flex items-center gap-2">
          <ChevronRight
            v-if="isMultiStyle"
            class="h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200"
            :class="{ 'rotate-90': open }"
          />
          <div v-else class="w-4 shrink-0" />

          <!-- Preview -->
          <span
            class="flex-1 truncate leading-relaxed"
            :style="{
              fontSize: `${previewSize}px`,
              fontFamily: previewFontId
                ? `'${getFontFamily(previewFontId)}', sans-serif`
                : 'sans-serif',
            }"
          >
            {{ previewText || family.name }}
          </span>
        </div>
      </component>

      <div class="pr-3 shrink-0">
        <DeviceInstallSheet
          v-if="familyFontIds.length > 0"
          :font-ids="familyFontIds"
          trigger-variant="icon"
        />
      </div>
    </div>

    <!-- Expanded members -->
    <div v-if="isMultiStyle && open">
      <!-- Loading skeleton -->
      <div
        v-if="loadingMembers && members.length === 0"
        class="space-y-1 pb-2"
      >
        <Skeleton
          v-for="i in Math.min(family.styleCount, 4)"
          :key="i"
          class="mx-4 h-14"
        />
      </div>

      <!-- Error state -->
      <div
        v-else-if="fetchError"
        class="flex items-center gap-2 px-4 py-3 pl-10"
      >
        <span class="text-sm text-muted-foreground"
          >Erreur de chargement</span
        >
        <Button variant="ghost" size="icon-sm" @click="retry">
          <RotateCcw class="h-3.5 w-3.5" />
        </Button>
      </div>

      <!-- Members list -->
      <div v-else class="pb-2">
        <FontStyleRow
          v-for="member in members"
          :key="member.fontId"
          :member="member"
          :preview-text="previewText"
          :preview-size="previewSize"
          :family-name="family.name"
          :observe="observe"
          :unobserve="unobserve"
          :get-font-family="getFontFamily"
        />
      </div>
    </div>
  </div>
</template>
