<script setup lang="ts">
import { computed } from 'vue'
import { Copy, Download, Server, Check } from 'lucide-vue-next'
import { ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useWsStore } from '@/stores/ws'
import { storeToRefs } from 'pinia'

const wsStore = useWsStore()
const { status } = storeToRefs(wsStore)

const serverUrl = computed(() => window.location.origin)
const copied = ref(false)

async function copyUrl() {
  await navigator.clipboard.writeText(serverUrl.value)
  copied.value = true
  setTimeout(() => (copied.value = false), 2000)
}

const wsStatusLabel = computed(() => {
  switch (status.value) {
    case 'connected':
      return 'Connecté'
    case 'connecting':
      return 'Connexion...'
    default:
      return 'Déconnecté'
  }
})

const wsStatusVariant = computed<'default' | 'secondary' | 'destructive'>(() => {
  switch (status.value) {
    case 'connected':
      return 'default'
    case 'connecting':
      return 'secondary'
    default:
      return 'destructive'
  }
})
</script>

<template>
  <div>
    <h1 class="text-3xl font-bold tracking-tight">Paramètres</h1>
    <p class="text-muted-foreground mt-1">
      Configuration de votre instance FontSync.
    </p>

    <div class="mt-8 space-y-6">
      <!-- Server info -->
      <div class="rounded-xl border bg-card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <Server class="h-5 w-5 text-muted-foreground" />
          <h2 class="text-lg font-semibold">Serveur</h2>
        </div>

        <div class="space-y-3">
          <div>
            <p class="text-sm text-muted-foreground mb-1">URL du serveur</p>
            <div class="flex items-center gap-2">
              <code
                class="flex-1 rounded-lg border bg-muted/50 px-3 py-2 text-sm font-mono"
              >
                {{ serverUrl }}
              </code>
              <Button variant="outline" size="icon" @click="copyUrl">
                <Check v-if="copied" class="h-4 w-4 text-green-500" />
                <Copy v-else class="h-4 w-4" />
              </Button>
            </div>
          </div>

          <div>
            <p class="text-sm text-muted-foreground mb-1">WebSocket</p>
            <Badge :variant="wsStatusVariant">{{ wsStatusLabel }}</Badge>
          </div>
        </div>
      </div>

      <!-- Agent download -->
      <div class="rounded-xl border bg-card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <Download class="h-5 w-5 text-muted-foreground" />
          <h2 class="text-lg font-semibold">Agent de synchronisation</h2>
        </div>

        <p class="text-sm text-muted-foreground">
          L'agent FontSync tourne en arrière-plan sur votre Mac. Il détecte
          automatiquement les nouvelles polices installées et les synchronise
          avec le serveur.
        </p>

        <Button variant="outline" disabled>
          <Download class="mr-2 h-4 w-4" />
          Télécharger FontSync.app pour macOS
        </Button>
        <p class="text-xs text-muted-foreground">
          Le téléchargement de l'agent sera disponible prochainement.
        </p>
      </div>
    </div>
  </div>
</template>
