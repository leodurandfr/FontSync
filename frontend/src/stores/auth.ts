import { computed, ref } from "vue";
import { defineStore } from "pinia";
import type { AuthStatus, Me } from "@/types/api";

/** Token d'instance HÉRITÉ (`FONTSYNC_TOKEN`), d'avant les comptes. */
const STORAGE_KEY = "fontsync_token";

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    // localStorage indisponible (mode privé, sandbox) → pas de token mémorisé.
    return null;
  }
}

function storeToken(value: string | null) {
  try {
    if (value) localStorage.setItem(STORAGE_KEY, value);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Pas de persistance possible : la valeur reste valable pour la session.
  }
}

/** Erreur d'un appel d'authentification, avec le `detail` du serveur. */
export class AuthError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "AuthError";
    this.status = status;
  }
}

/**
 * Qui est connecté, et quel écran montrer avant l'application.
 *
 * - `checking` : on interroge `GET /api/auth/status` ;
 * - `setup` : aucun compte n'existe, on crée l'administrateur ;
 * - `login` : connexion par email + mot de passe ;
 * - `ready` : une identité valide, l'application s'affiche.
 *
 * La session navigateur vit dans un cookie `HttpOnly` posé par le serveur : le
 * JavaScript ne voit jamais le secret. Le token d'instance hérité reste géré
 * (en `Authorization: Bearer`) le temps de la migration ; il est oublié dès
 * qu'une vraie session est ouverte.
 */
export const useAuthStore = defineStore("auth", () => {
  const token = ref<string | null>(readStoredToken());
  const phase = ref<"checking" | "setup" | "login" | "ready">("checking");
  const me = ref<Me | null>(null);
  const setupNeedsLegacyToken = ref(false);
  const legacyTokenEnabled = ref(false);
  const unreachable = ref(false);

  const needsAuth = computed(() => phase.value !== "ready");
  /** Droits d'administration (jamais pour un jeton d'appareil). */
  const isAdmin = computed(
    () => me.value?.role === "admin" && me.value.kind !== "device",
  );

  function headers(extra?: HeadersInit): Headers {
    const h = new Headers(extra);
    if (token.value) h.set("Authorization", `Bearer ${token.value}`);
    return h;
  }

  function apply(status: AuthStatus) {
    setupNeedsLegacyToken.value = status.setupNeedsLegacyToken;
    legacyTokenEnabled.value = status.legacyTokenEnabled;
    me.value = status.me;
    if (status.setupRequired) phase.value = "setup";
    else if (status.me) phase.value = "ready";
    else phase.value = "login";
  }

  /** Relit l'état de l'instance et l'identité courante. */
  async function refresh(): Promise<void> {
    try {
      const res = await fetch("/api/auth/status", { headers: headers() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      unreachable.value = false;
      apply((await res.json()) as AuthStatus);
    } catch {
      unreachable.value = true;
      phase.value = "login";
    }
  }

  async function post(path: string, body: unknown): Promise<Response> {
    const res = await fetch(path, {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      const detail = data?.detail;
      throw new AuthError(
        typeof detail === "string" ? detail : `HTTP ${res.status}`,
        res.status,
      );
    }
    return res;
  }

  /** Une vraie session est ouverte : le token hérité n'est plus utile ici. */
  async function onSignedIn() {
    token.value = null;
    storeToken(null);
    await refresh();
  }

  async function setup(email: string, password: string, legacyToken?: string) {
    await post("/api/auth/setup", {
      email,
      password,
      legacyToken: legacyToken || token.value || undefined,
    });
    await onSignedIn();
  }

  async function login(email: string, password: string) {
    await post("/api/auth/login", { email, password });
    await onSignedIn();
  }

  async function acceptInvitation(invitationToken: string, password: string) {
    await post("/api/auth/invitations/accept", {
      token: invitationToken,
      password,
    });
    await onSignedIn();
  }

  async function lookupInvitation(
    invitationToken: string,
  ): Promise<{ email: string; role: string }> {
    const res = await post("/api/auth/invitations/lookup", {
      token: invitationToken,
    });
    return res.json();
  }

  /** Connexion par le token d'instance hérité (migration). */
  async function loginWithToken(value: string) {
    const candidate = value.trim();
    const res = await fetch("/api/stats", {
      headers: { Authorization: `Bearer ${candidate}` },
    });
    if (!res.ok) throw new AuthError(`HTTP ${res.status}`, res.status);
    token.value = candidate;
    storeToken(candidate);
    await refresh();
  }

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => null);
    token.value = null;
    storeToken(null);
    me.value = null;
    await refresh();
  }

  /** Un 401 REST ou une fermeture WebSocket `1008` : on revérifie l'état. */
  function markUnauthorized() {
    if (phase.value === "ready") phase.value = "checking";
    void refresh();
  }

  return {
    token,
    phase,
    me,
    setupNeedsLegacyToken,
    legacyTokenEnabled,
    unreachable,
    needsAuth,
    isAdmin,
    refresh,
    setup,
    login,
    acceptInvitation,
    lookupInvitation,
    loginWithToken,
    logout,
    markUnauthorized,
  };
});
