<script setup lang="ts">
import { ref } from "vue";
import { KeyRound, Loader2, Type } from "lucide-vue-next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const tokenInput = ref(auth.token ?? "");
const validating = ref(false);
const errorMsg = ref<string | null>(null);

async function submit() {
  const candidate = tokenInput.value.trim();
  if (!candidate) {
    errorMsg.value = "Veuillez saisir un token.";
    return;
  }
  validating.value = true;
  errorMsg.value = null;
  try {
    // Validation directe contre une route protégée — `fetch` brut (pas
    // `apiFetch`) pour ne pas réutiliser le token stocké ni redéclencher
    // `markUnauthorized` sur un 401 attendu.
    const res = await fetch("/api/stats", {
      headers: { Authorization: `Bearer ${candidate}` },
    });
    if (res.status === 401) {
      errorMsg.value = "Token invalide.";
      return;
    }
    if (!res.ok) {
      errorMsg.value = `Erreur serveur (${res.status}).`;
      return;
    }
    auth.setToken(candidate);
  } catch {
    errorMsg.value = "Serveur injoignable. Vérifiez l'URL et le réseau.";
  } finally {
    validating.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-background p-4">
    <div class="w-full max-w-sm space-y-6 rounded-xl border bg-card p-8">
      <div class="flex flex-col items-center gap-3 text-center">
        <div
          class="flex h-11 w-11 items-center justify-center rounded-xl bg-foreground text-background"
        >
          <Type class="h-5 w-5" />
        </div>
        <div>
          <h1 class="text-xl font-bold tracking-tight">FontSync</h1>
          <p class="mt-1 text-sm text-muted-foreground">
            Saisissez le token d'accès de votre instance pour continuer.
          </p>
        </div>
      </div>

      <form class="space-y-3" @submit.prevent="submit">
        <div class="space-y-1.5">
          <Label for="token">Token serveur</Label>
          <Input
            id="token"
            v-model="tokenInput"
            type="password"
            autocomplete="current-password"
            placeholder="FONTSYNC_TOKEN"
            :disabled="validating"
            autofocus
          />
        </div>

        <p v-if="errorMsg" class="text-sm text-destructive">{{ errorMsg }}</p>

        <Button type="submit" class="w-full" :disabled="validating">
          <Loader2 v-if="validating" class="mr-2 h-4 w-4 animate-spin" />
          {{ validating ? "Vérification…" : "Se connecter" }}
        </Button>
      </form>

      <p
        class="flex items-center justify-center gap-1.5 text-xs text-muted-foreground"
      >
        <KeyRound class="h-3 w-3 shrink-0" />
        Défini par <code class="font-mono">FONTSYNC_TOKEN</code> côté serveur.
      </p>
    </div>
  </div>
</template>
