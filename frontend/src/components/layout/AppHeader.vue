<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import { Settings, Loader2 } from "lucide-vue-next";
import { Button } from "@/components/ui/button";
import { useWsStore } from "@/stores/ws";

const route = useRoute();
const wsStore = useWsStore();

const onSettings = computed(() => route.path.startsWith("/settings"));
</script>

<template>
  <header class="flex h-14 shrink-0 items-center justify-between border-b px-4">
    <!-- Wordmark -->
    <RouterLink to="/" class="shrink-0">
      <span class="text-base font-bold tracking-tight">FontSync</span>
    </RouterLink>

    <!-- Right: connection status + settings -->
    <div class="flex shrink-0 items-center gap-2">
      <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
        <template v-if="wsStore.status === 'connected'">
          <span class="h-2 w-2 rounded-full bg-green-500" />
          <span class="hidden sm:inline">Connecté</span>
        </template>
        <template v-else>
          <Loader2 class="h-3 w-3 animate-spin text-amber-500" />
          <span class="hidden sm:inline">Reconnexion…</span>
        </template>
      </div>

      <Button
        as-child
        variant="ghost"
        size="icon"
        :class="onSettings ? 'bg-accent text-accent-foreground' : ''"
        aria-label="Paramètres"
      >
        <RouterLink to="/settings">
          <Settings class="h-4 w-4" />
        </RouterLink>
      </Button>
    </div>
  </header>
</template>
