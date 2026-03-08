<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { RouterLink } from "vue-router";
import { ArrowRight } from "lucide-vue-next";
import { useFontsStore } from "@/stores/fonts";
import { useDevicesStore } from "@/stores/devices";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Font } from "@/types/api";

const fontsStore = useFontsStore();
const devicesStore = useDevicesStore();

const recentFonts = ref<Font[]>([]);
const recentLoading = ref(false);

const onlineDevices = computed(() =>
  devicesStore.devices.filter((d) => devicesStore.isOnline(d.id)),
);

async function fetchRecentFonts() {
  recentLoading.value = true;
  try {
    const res = await fetch(
      "/api/fonts?sort=created_at&order=desc&per_page=5",
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    recentFonts.value = data.items ?? [];
  } catch {
    // Silent fail — dashboard is non-critical
  } finally {
    recentLoading.value = false;
  }
}

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  if (diff < 0 || diff < 60_000) return "À l'instant";
  if (diff < 3_600_000) return `Il y a ${Math.floor(diff / 60_000)} min`;
  if (diff < 86_400_000) return `Il y a ${Math.floor(diff / 3_600_000)} h`;
  return `Il y a ${Math.floor(diff / 86_400_000)} j`;
}

onMounted(() => {
  fetchRecentFonts();
  if (devicesStore.devices.length === 0 && !devicesStore.loading) {
    devicesStore.fetchDevices();
  }
});
</script>

<template>
  <div>
    <h1 class="text-3xl font-bold tracking-tight">Dashboard</h1>
    <p class="text-muted-foreground mt-1">
      Vue d'ensemble de votre bibliothèque de polices.
    </p>

    <!-- Stats cards -->
    <div class="mt-8 grid gap-4 md:grid-cols-3">
      <div class="rounded-xl border bg-card p-6">
        <p class="text-sm font-medium text-muted-foreground">Polices</p>
        <p class="text-3xl font-bold tracking-tight mt-1">
          {{ fontsStore.total }}
        </p>
      </div>
      <div class="rounded-xl border bg-card p-6">
        <p class="text-sm font-medium text-muted-foreground">Appareils</p>
        <p class="text-3xl font-bold tracking-tight mt-1">
          {{ devicesStore.devices.length }}
        </p>
      </div>
      <div class="rounded-xl border bg-card p-6">
        <p class="text-sm font-medium text-muted-foreground">Connectés</p>
        <p class="text-3xl font-bold tracking-tight mt-1">
          {{ devicesStore.onlineCount }}
        </p>
      </div>
    </div>

    <!-- Recent fonts -->
    <section class="mt-10">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold">Dernières polices ajoutées</h2>
        <Button variant="ghost" size="sm" as-child>
          <RouterLink :to="{ name: 'fonts' }">
            Voir tout
            <ArrowRight class="ml-1 h-4 w-4" />
          </RouterLink>
        </Button>
      </div>

      <div v-if="recentLoading" class="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Skeleton v-for="i in 5" :key="i" class="h-24 rounded-xl" />
      </div>

      <div
        v-else-if="recentFonts.length === 0"
        class="rounded-xl border border-dashed p-8 text-center"
      >
        <p class="text-sm text-muted-foreground">Aucune police pour l'instant.</p>
      </div>

      <div v-else class="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <RouterLink
          v-for="font in recentFonts"
          :key="font.id"
          :to="{ name: 'font-detail', params: { id: font.id } }"
          class="rounded-xl border bg-card p-4 transition-colors hover:border-foreground/20"
        >
          <p class="font-semibold truncate text-sm">
            {{ font.familyName ?? font.originalFilename }}
          </p>
          <p class="text-xs text-muted-foreground truncate mt-0.5">
            {{ font.subfamilyName ?? font.fileFormat.toUpperCase() }}
          </p>
          <div class="mt-2 flex items-center gap-1.5">
            <Badge variant="outline" class="text-[10px]">
              {{ font.fileFormat.toUpperCase() }}
            </Badge>
            <span class="text-[10px] text-muted-foreground">
              {{ formatRelativeTime(font.createdAt) }}
            </span>
          </div>
        </RouterLink>
      </div>
    </section>

    <!-- Online devices -->
    <section class="mt-10">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold">Appareils en ligne</h2>
        <Button variant="ghost" size="sm" as-child>
          <RouterLink :to="{ name: 'devices' }">
            Voir tout
            <ArrowRight class="ml-1 h-4 w-4" />
          </RouterLink>
        </Button>
      </div>

      <div
        v-if="onlineDevices.length === 0"
        class="rounded-xl border border-dashed p-8 text-center"
      >
        <p class="text-sm text-muted-foreground">
          Aucun appareil connecté.
        </p>
      </div>

      <div v-else class="space-y-2">
        <div
          v-for="device in onlineDevices"
          :key="device.id"
          class="flex items-center gap-3 rounded-xl border bg-card px-4 py-3"
        >
          <span class="h-2 w-2 shrink-0 rounded-full bg-green-500" />
          <span class="font-medium text-sm">{{ device.name }}</span>
          <span class="text-xs text-muted-foreground">
            {{ device.os }}
          </span>
        </div>
      </div>
    </section>
  </div>
</template>
