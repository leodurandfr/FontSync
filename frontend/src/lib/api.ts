import { useAuthStore } from "@/stores/auth";

/** Levée par `apiFetch` sur un `401` : l'écran de connexion reprend la main. */
export class UnauthorizedError extends Error {
  constructor() {
    super("Unauthorized");
    this.name = "UnauthorizedError";
  }
}

/**
 * `fetch` authentifié.
 *
 * La session navigateur voyage seule, dans son cookie `HttpOnly`. Le token
 * d'instance hérité, s'il est encore mémorisé, est ajouté en
 * `Authorization: Bearer`. Un `401` marque la session comme non autorisée
 * (l'écran de connexion reprend la main) puis lève `UnauthorizedError`. Les autres réponses — y
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

/**
 * Appel JSON authentifié : envoie `body` en JSON, rend la réponse décodée (ou
 * `null` pour un `204`), et lève une `Error` portant le `detail` du serveur.
 */
export async function apiJson<T>(
  input: string,
  method: string = "GET",
  body?: unknown,
): Promise<T> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const res = await apiFetch(input, init);
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
  }
  if (res.status === 204) return null as T;
  return (await res.json()) as T;
}
