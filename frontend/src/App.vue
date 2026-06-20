<script setup lang="ts">
import { storeToRefs } from "pinia";
import AppShell from "@/components/layout/AppShell.vue";
import TokenGate from "@/components/auth/TokenGate.vue";
import { useAuthStore } from "@/stores/auth";

// Tant qu'aucun token valide n'est connu (premier lancement, ou 401 / WS 1008
// en cours de session), on remplace toute l'app par l'écran de saisie : aucun
// appel réseau n'est tenté avant d'avoir un token (P1.4).
const { needsToken } = storeToRefs(useAuthStore());
</script>

<template>
  <TokenGate v-if="needsToken" />
  <AppShell v-else />
</template>
