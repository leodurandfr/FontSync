import { ref } from "vue";
import { defineStore } from "pinia";

const STORAGE_KEY = "fontsync_token";

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    // localStorage indisponible (mode privé, sandbox) → pas de token mémorisé.
    return null;
  }
}

/**
 * Token partagé d'instance côté frontend (P1.4, PLAN-PUBLICATION.md).
 *
 * Le token est saisi par l'utilisateur, mémorisé dans `localStorage`, et injecté
 * dans tous les appels réseau (`apiFetch` + WebSocket). `needsToken` pilote
 * l'écran de saisie : vrai au premier lancement (aucun token), ou rebasculé à
 * vrai sur un `401` REST / une fermeture WebSocket `1008` (token absent, devenu
 * invalide, ou tourné côté serveur).
 */
export const useAuthStore = defineStore("auth", () => {
  const token = ref<string | null>(readStoredToken());
  const needsToken = ref<boolean>(!token.value);

  function setToken(value: string) {
    const trimmed = value.trim();
    token.value = trimmed;
    try {
      localStorage.setItem(STORAGE_KEY, trimmed);
    } catch {
      // Pas de persistance possible : le token reste valable pour la session.
    }
    needsToken.value = false;
  }

  function clearToken() {
    token.value = null;
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
    needsToken.value = true;
  }

  /** Redemande le token (401 REST / preview / download, ou close WS 1008). */
  function markUnauthorized() {
    needsToken.value = true;
  }

  return { token, needsToken, setToken, clearToken, markUnauthorized };
});
