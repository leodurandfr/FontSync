<script setup lang="ts">
defineProps<{ id: string }>()
</script>

<template>
  <div>
    <h1 class="text-3xl font-bold tracking-tight">Détail de la police</h1>
    <p class="text-muted-foreground mt-1">Font ID : {{ id }}</p>
    <div class="mt-8 rounded-xl border bg-card p-6">
      <p class="text-muted-foreground text-sm">
        Le détail complet sera implémenté dans la prochaine phase.
      </p>
    </div>
  </div>
</template>
