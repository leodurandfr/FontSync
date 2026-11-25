<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import AppShell from "@/components/layout/AppShell.vue";
import AuthGate from "@/components/auth/AuthGate.vue";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const { needsAuth, phase, isAdmin } = storeToRefs(auth);
const route = useRoute();
const router = useRouter();

// Lien d'invitation `/invite#<jeton>` : le fragment n'est jamais envoyé au
// serveur, donc jamais journalisé. On le retire de l'URL dès qu'il est lu.
const invitationToken = ref<string | null>(null);
if (window.location.pathname === "/invite") {
  invitationToken.value = window.location.hash.slice(1) || null;
  void router.replace({ name: "fonts" });
}

// Page réservée ouverte avant que l'identité soit connue : on en sort.
watch([phase, isAdmin, () => route.meta.adminOnly], () => {
  if (phase.value === "ready" && route.meta.adminOnly && !isAdmin.value) {
    void router.replace({ name: "fonts" });
  }
});

function onInvitationDone() {
  invitationToken.value = null;
}

// Tant qu'aucune identité valide n'est connue, l'écran de connexion remplace
// toute l'app : aucun appel réseau n'est tenté avant.
onMounted(() => {
  void auth.refresh();
});
</script>

<template>
  <div
    v-if="phase === 'checking' && !invitationToken"
    class="min-h-screen bg-background"
  />
  <AuthGate
    v-else-if="needsAuth || invitationToken"
    :invitation-token="invitationToken"
    @invitation-done="onInvitationDone"
  />
  <AppShell v-else />
</template>
