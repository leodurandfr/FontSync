<script setup lang="ts">
import { onMounted } from 'vue'
import { useFontsStore } from '@/stores/fonts'

const fontsStore = useFontsStore()

onMounted(() => {
  fontsStore.fetchFonts()
})
</script>

<template>
  <div>
    <h1 class="text-3xl font-bold tracking-tight">Polices</h1>
    <p class="text-muted-foreground mt-1">
      Parcourez et gérez votre bibliothèque de polices.
    </p>

    <div class="mt-8">
      <div
        v-if="fontsStore.loading"
        class="text-muted-foreground text-sm"
      >
        Chargement...
      </div>
      <div
        v-else-if="fontsStore.fonts.length === 0"
        class="rounded-xl border border-dashed p-12 text-center"
      >
        <p class="text-muted-foreground">
          Aucune police dans la bibliothèque.
        </p>
        <p class="text-sm text-muted-foreground mt-1">
          Uploadez des fichiers ou connectez un agent pour commencer.
        </p>
      </div>
      <div
        v-else
        class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        <RouterLink
          v-for="font in fontsStore.fonts"
          :key="font.id"
          :to="{ name: 'font-detail', params: { id: font.id } }"
          class="group rounded-xl border bg-card p-5 transition-colors hover:border-foreground/20"
        >
          <p
            class="text-2xl font-semibold tracking-tight truncate"
            :title="font.familyName ?? font.originalFilename"
          >
            {{ font.familyName ?? font.originalFilename }}
          </p>
          <p class="text-sm text-muted-foreground mt-1">
            {{ font.subfamilyName ?? font.fileFormat.toUpperCase() }}
          </p>
        </RouterLink>
      </div>
    </div>
  </div>
</template>
