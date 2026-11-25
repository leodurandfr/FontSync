import { computed, ref } from "vue";
import { defineStore } from "pinia";
import type { AuthStatus, Me } from "@/types/api";

/** Ancienne clé du token d'instance, retirée au chargement (nettoyage). */
const FORMER_TOKEN_KEY = "fontsync_token";

function forgetFormerToken() {
  try {
    localStorage.removeItem(FORMER_TOKEN_KEY);
  } catch {
    // localStorage indisponible (mode privé, sandbox) : rien à nettoyer.
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
 * JavaScript ne voit jamais le secret.
 */
export const useAuthStore = defineStore("auth", () => {
  forgetFormerToken();
  const phase = ref<"checking" | "setup" | "login" | "ready">("checking");
  const me = ref<Me | null>(null);
  const unreachable = ref(false);

  const needsAuth = computed(() => phase.value !== "ready");
  /** Droits d'administration (jamais pour un jeton d'appareil). */
  const isAdmin = computed(
    () => me.value?.role === "admin" && me.value.kind !== "device",
  );

  function apply(status: AuthStatus) {
    me.value = status.me;
    if (status.setupRequired) phase.value = "setup";
    else if (status.me) phase.value = "ready";
    else phase.value = "login";
  }

  /** Relit l'état de l'instance et l'identité courante. */
  async function refresh(): Promise<void> {
    try {
      const res = await fetch("/api/auth/status");
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
      headers: { "Content-Type": "application/json" },
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

  async function setup(email: string, password: string) {
    await post("/api/auth/setup", { email, password });
    await refresh();
  }

  async function login(email: string, password: string) {
    await post("/api/auth/login", { email, password });
    await refresh();
  }

  async function acceptInvitation(
    invitationToken: string,
    email: string,
    password: string,
  ) {
    await post("/api/auth/invitations/accept", {
      token: invitationToken,
      email: email || undefined,
      password,
    });
    await refresh();
  }

  async function lookupInvitation(
    invitationToken: string,
  ): Promise<{ email: string | null; role: string }> {
    const res = await post("/api/auth/invitations/lookup", {
      token: invitationToken,
    });
    return res.json();
  }

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => null);
    me.value = null;
    await refresh();
  }

  /** Un 401 REST ou une fermeture WebSocket `1008` : on revérifie l'état. */
  function markUnauthorized() {
    if (phase.value === "ready") phase.value = "checking";
    void refresh();
  }

  return {
    phase,
    me,
    unreachable,
    needsAuth,
    isAdmin,
    refresh,
    setup,
    login,
    acceptInvitation,
    lookupInvitation,
    logout,
    markUnauthorized,
  };
});
