import { useAuthStore } from "@/stores/auth";

/** Levée par `apiFetch` sur un `401` : l'écran de saisie du token reprend la main. */
export class UnauthorizedError extends Error {
  constructor() {
    super("Unauthorized");
    this.name = "UnauthorizedError";
  }
}

/**
 * `fetch` authentifié par le token d'instance (P1.4).
 *
 * Injecte `Authorization: Bearer <token>` quand un token est connu, et
 * intercepte le `401` : marque la session comme non autorisée (réaffiche la
 * saisie du token) puis lève `UnauthorizedError`. Les autres réponses — y
 * compris les erreurs HTTP non-401 — sont renvoyées telles quelles, à charge
 * de l'appelant de vérifier `res.ok`. Le `signal` d'annulation et toutes les
 * autres options de `RequestInit` sont préservés.
 */
export async function apiFetch(
  input: string,
  init: RequestInit = {},
): Promise<Response> {
  const auth = useAuthStore();
  const headers = new Headers(init.headers);
  if (auth.token) {
    headers.set("Authorization", `Bearer ${auth.token}`);
  }

  const res = await fetch(input, { ...init, headers });

  if (res.status === 401) {
    auth.markUnauthorized();
    throw new UnauthorizedError();
  }

  return res;
}
