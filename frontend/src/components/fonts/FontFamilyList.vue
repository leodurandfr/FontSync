<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { Loader2 } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { useFamiliesStore } from "@/stores/families";
import { useFamilyFiltersStore } from "@/stores/familyFilters";
import { useFontPreview } from "@/composables/useFontPreview";
import FontFamilyGroup from "./FontFamilyGroup.vue";
import { Skeleton } from "@/components/ui/skeleton";
import type { FontLayout, Typo } from "./types";

const { t } = useI18n();

defineProps<{
  typo: Typo;
  layout: FontLayout;
}>();

const familiesStore = useFamiliesStore();
const filtersStore = useFamilyFiltersStore();
const { getFontFamily, isFontReady, observe, unobserve, preload } =
  useFontPreview();

const sentinelRef = ref<HTMLElement | null>(null);
let scrollObserver: IntersectionObserver | null = null;

onMounted(() => {
  familiesStore.fetchFamilies(filtersStore.toFilters());

  scrollObserver = new IntersectionObserver(
    (entries) => {
      if (
        entries[0]?.isIntersecting &&
        familiesStore.hasMore &&
        !familiesStore.loadingMore
      ) {
        familiesStore.fetchMore(filtersStore.toFilters());
      }
    },
    // On charge la page suivante très en avance pour que les cartes soient
    // montées avant d'entrer dans la zone de préchargement des fontes (1200px).
    { rootMargin: "1200px" },
  );

  if (sentinelRef.value) {
    scrollObserver.observe(sentinelRef.value);
  }
});

onBeforeUnmount(() => {
  scrollObserver?.disconnect();
});

watch(sentinelRef, (el) => {
  if (el) scrollObserver?.observe(el);
});
</script>

<template>
  <!-- Loading skeleton -->
  <div
    v-if="familiesStore.loading && familiesStore.families.length === 0"
    class="divide-y divide-separator border-y border-separator"
  >
    <div v-for="i in 6" :key="i" class="px-8 py-7">
      <Skeleton class="mb-4 h-3 w-40" />
      <Skeleton class="h-10 w-2/3" />
    </div>
  </div>

  <!-- Empty state -->
  <div
    v-else-if="familiesStore.isEmpty"
    class="flex h-48 flex-col items-center justify-center gap-2"
  >
    <p class="text-[13px] text-muted-foreground">
      {{ t("fonts.noFontsFound") }}
    </p>
    <p class="text-[11px] text-foreground-subtle">
      {{ t("fonts.adjustFilters") }}
    </p>
  </div>

  <!-- Family list -->
  <template v-else>
    <ul class="divide-y divide-separator border-y border-separator">
      <FontFamilyGroup
        v-for="family in familiesStore.families"
        :key="family.id"
        :family="family"
        :typo="typo"
        :layout="layout"
        :observe="observe"
        :unobserve="unobserve"
        :get-font-family="getFontFamily"
        :is-font-ready="isFontReady"
        :preload="preload"
      />
    </ul>

    <!-- Infinite scroll sentinel -->
    <div ref="sentinelRef" class="flex justify-center py-8">
      <Loader2
        v-if="familiesStore.loadingMore"
        class="size-5 animate-spin text-muted-foreground"
      />
    </div>
  </template>
</template>
