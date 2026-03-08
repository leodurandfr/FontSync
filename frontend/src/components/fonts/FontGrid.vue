<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { Loader2 } from "lucide-vue-next";
import { useFontsStore } from "@/stores/fonts";
import { useFiltersStore } from "@/stores/filters";
import { useFontPreview } from "@/composables/useFontPreview";
import FontCard from "./FontCard.vue";
import { Skeleton } from "@/components/ui/skeleton";

const props = defineProps<{
  previewText: string;
}>();

const fontsStore = useFontsStore();
const filtersStore = useFiltersStore();
const { getFontFamily, observe, unobserve } = useFontPreview();

const sentinelRef = ref<HTMLElement | null>(null);
let scrollObserver: IntersectionObserver | null = null;

onMounted(() => {
  fontsStore.fetchFonts(filtersStore.toFilters());

  scrollObserver = new IntersectionObserver(
    (entries) => {
      if (
        entries[0]?.isIntersecting &&
        fontsStore.hasMore &&
        !fontsStore.loadingMore
      ) {
        fontsStore.fetchMore(filtersStore.toFilters());
      }
    },
    { rootMargin: "400px" },
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
    v-if="fontsStore.loading && fontsStore.fonts.length === 0"
    class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
  >
    <div v-for="i in 9" :key="i" class="rounded-xl border bg-card p-5">
      <Skeleton class="h-20 w-full mb-4" />
      <Skeleton class="h-5 w-3/4 mb-2" />
      <Skeleton class="h-4 w-1/2 mb-3" />
      <div class="flex gap-1.5">
        <Skeleton class="h-5 w-16 rounded-full" />
        <Skeleton class="h-5 w-20 rounded-full" />
      </div>
    </div>
  </div>

  <!-- Empty state -->
  <div
    v-else-if="fontsStore.isEmpty"
    class="rounded-xl border border-dashed p-12 text-center"
  >
    <p class="text-muted-foreground">Aucune police dans la bibliothèque.</p>
    <p class="text-sm text-muted-foreground mt-1">
      Uploadez des fichiers ou connectez un agent pour commencer.
    </p>
  </div>

  <!-- Grid -->
  <template v-else>
    <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <FontCard
        v-for="font in fontsStore.fonts"
        :key="font.id"
        :font="font"
        :preview-text="previewText"
        :observe="observe"
        :unobserve="unobserve"
        :get-font-family="getFontFamily"
      />
    </div>

    <!-- Infinite scroll sentinel -->
    <div ref="sentinelRef" class="flex justify-center py-8">
      <Loader2
        v-if="fontsStore.loadingMore"
        class="h-5 w-5 animate-spin text-muted-foreground"
      />
    </div>
  </template>
</template>
