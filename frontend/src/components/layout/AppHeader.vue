<script setup lang="ts">
import { ref, watch } from 'vue'
import { Search, Wifi, WifiOff, Loader2 } from 'lucide-vue-next'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { Separator } from '@/components/ui/separator'
import { Input } from '@/components/ui/input'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useWsStore } from '@/stores/ws'
import { useFiltersStore } from '@/stores/filters'
import { storeToRefs } from 'pinia'

const wsStore = useWsStore()
const filtersStore = useFiltersStore()
const { status } = storeToRefs(wsStore)

const searchInput = ref(filtersStore.search)
let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(searchInput, (val) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    filtersStore.search = val
    filtersStore.page = 1
  }, 300)
})
</script>

<template>
  <header class="flex h-14 shrink-0 items-center gap-3 border-b px-4">
    <SidebarTrigger class="-ml-1" />
    <Separator orientation="vertical" class="h-5" />

    <div class="relative flex-1 max-w-md">
      <Search class="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        v-model="searchInput"
        type="search"
        placeholder="Rechercher une police..."
        class="pl-9 h-9"
      />
    </div>

    <div class="ml-auto flex items-center gap-2">
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger as-child>
            <div
              class="flex h-8 w-8 items-center justify-center rounded-full transition-colors"
              :class="{
                'text-emerald-500': status === 'connected',
                'text-destructive': status === 'disconnected',
                'text-muted-foreground': status === 'connecting',
              }"
            >
              <Wifi v-if="status === 'connected'" class="h-4 w-4" />
              <Loader2 v-else-if="status === 'connecting'" class="h-4 w-4 animate-spin" />
              <WifiOff v-else class="h-4 w-4" />
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p v-if="status === 'connected'">Connecté au serveur</p>
            <p v-else-if="status === 'connecting'">Connexion en cours...</p>
            <p v-else>Déconnecté du serveur</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  </header>
</template>
