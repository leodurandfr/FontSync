<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { Loader2 } from "lucide-vue-next";
import { useFamiliesStore } from "@/stores/families";
import { useFamilyFiltersStore } from "@/stores/familyFilters";
import { useFontPreview } from "@/composables/useFontPreview";
import FamilyCard from "./FamilyCard.vue";
import { Skeleton } from "@/components/ui/skeleton";

const props = defineProps<{
  previewText: string;
}>();

const familiesStore = useFamiliesStore();
const filtersStore = useFamilyFiltersStore();
const { getFontFamily, observe, unobserve } = useFontPreview();

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
    v-if="familiesStore.loading && familiesStore.families.length === 0"
    class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
  >
    <div v-for="i in 6" :key="i" class="rounded-xl border bg-card p-5">
      <Skeleton class="h-16 w-full mb-4" />
      <Skeleton class="h-5 w-3/4 mb-2" />
      <Skeleton class="h-4 w-1/3 mb-3" />
      <div class="flex gap-1.5">
        <Skeleton class="h-5 w-16 rounded-full" />
      </div>
    </div>
  </div>

  <!-- Empty state -->
  <div
    v-else-if="familiesStore.isEmpty"
    class="rounded-xl border border-dashed p-12 text-center"
  >
    <p class="text-muted-foreground">Aucune famille dans la bibliotheque.</p>
    <p class="text-sm text-muted-foreground mt-1">
      Utilisez le regroupement automatique ou creez une famille manuellement.
    </p>
  </div>

  <!-- Grid -->
  <template v-else>
    <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <FamilyCard
        v-for="family in familiesStore.families"
        :key="family.id"
        :family="family"
        :preview-text="previewText"
        :observe="observe"
        :unobserve="unobserve"
        :get-font-family="getFontFamily"
      />
    </div>

    <!-- Infinite scroll sentinel -->
    <div ref="sentinelRef" class="flex justify-center py-8">
      <Loader2
        v-if="familiesStore.loadingMore"
        class="h-5 w-5 animate-spin text-muted-foreground"
      />
    </div>
  </template>
</template>
