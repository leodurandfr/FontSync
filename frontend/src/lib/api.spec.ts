import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { apiFetch, UnauthorizedError } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

function fetchReturning(status: number) {
  return vi.fn().mockResolvedValue(new Response(null, { status }));
}

describe("apiFetch (P1.4)", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("ajoute l'en-tête Bearer quand un token est connu", async () => {
    useAuthStore().setToken("secret");
    const fetchMock = fetchReturning(200);
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/stats");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer secret",
    );
  });

  it("n'ajoute pas d'en-tête Bearer en l'absence de token", async () => {
    const fetchMock = fetchReturning(200);
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/stats");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).has("Authorization")).toBe(false);
  });

  it("sur 401 : marque non autorisé et lève UnauthorizedError", async () => {
    const auth = useAuthStore();
    auth.setToken("secret");
    expect(auth.needsToken).toBe(false);
    vi.stubGlobal("fetch", fetchReturning(401));

    await expect(apiFetch("/api/stats")).rejects.toBeInstanceOf(
      UnauthorizedError,
    );
    expect(auth.needsToken).toBe(true);
  });

  it("laisse passer les réponses non-401 (l'appelant vérifie res.ok)", async () => {
    vi.stubGlobal("fetch", fetchReturning(500));
    const res = await apiFetch("/api/stats");
    expect(res.status).toBe(500);
    expect(useAuthStore().needsToken).toBe(true); // pas de token → reste à true
  });

  it("préserve la méthode et le signal d'annulation", async () => {
    useAuthStore().setToken("secret");
    const fetchMock = fetchReturning(200);
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await apiFetch("/api/fonts", {
      method: "POST",
      signal: controller.signal,
    });

    const [input, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(input).toBe("/api/fonts");
    expect(init.method).toBe("POST");
    expect(init.signal).toBe(controller.signal);
  });
});
