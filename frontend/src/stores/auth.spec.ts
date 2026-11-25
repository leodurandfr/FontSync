import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { AuthError, useAuthStore } from "@/stores/auth";
import type { AuthStatus } from "@/types/api";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function status(partial: Partial<AuthStatus>): AuthStatus {
  return {
    setupRequired: false,
    setupNeedsLegacyToken: false,
    legacyTokenEnabled: false,
    me: null,
    ...partial,
  };
}

const ADMIN_ME = {
  kind: "web" as const,
  role: "admin" as const,
  user: null,
  deviceId: null,
};

describe("auth store (comptes)", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("commence en vérification, sans identité", () => {
    const auth = useAuthStore();
    expect(auth.phase).toBe("checking");
    expect(auth.needsAuth).toBe(true);
    expect(auth.isAdmin).toBe(false);
  });

  it("aucun compte : propose la création de l'admin", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(json(status({ setupRequired: true }))),
    );
    const auth = useAuthStore();
    await auth.refresh();
    expect(auth.phase).toBe("setup");
  });

  it("comptes existants sans session : écran de connexion", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(status({}))));
    const auth = useAuthStore();
    await auth.refresh();
    expect(auth.phase).toBe("login");
  });

  it("session valide : l'application s'affiche", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(json(status({ me: ADMIN_ME }))),
    );
    const auth = useAuthStore();
    await auth.refresh();
    expect(auth.phase).toBe("ready");
    expect(auth.needsAuth).toBe(false);
    expect(auth.isAdmin).toBe(true);
  });

  it("un jeton d'appareil n'a jamais les droits d'admin", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          json(status({ me: { ...ADMIN_ME, kind: "device" } })),
        ),
    );
    const auth = useAuthStore();
    await auth.refresh();
    expect(auth.isAdmin).toBe(false);
  });

  it("envoie le token hérité mémorisé à la vérification", async () => {
    localStorage.setItem("fontsync_token", "abc");
    setActivePinia(createPinia());
    const fetchMock = vi.fn().mockResolvedValue(json(status({})));
    vi.stubGlobal("fetch", fetchMock);
    await useAuthStore().refresh();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer abc");
  });

  it("connexion réussie : oublie le token hérité", async () => {
    localStorage.setItem("fontsync_token", "abc");
    setActivePinia(createPinia());
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(json({}))
        .mockResolvedValueOnce(json(status({ me: ADMIN_ME }))),
    );
    const auth = useAuthStore();
    await auth.login("admin@example.test", "motdepasse-long");
    expect(auth.token).toBeNull();
    expect(localStorage.getItem("fontsync_token")).toBeNull();
    expect(auth.phase).toBe("ready");
  });

  it("connexion refusée : AuthError avec le statut", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(json({ detail: "Identifiants invalides" }, 401)),
    );
    const auth = useAuthStore();
    const err = await auth.login("a@b.c", "x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(AuthError);
    expect((err as AuthError).status).toBe(401);
  });

  it("serveur injoignable : écran de connexion avec l'alerte", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    const auth = useAuthStore();
    await auth.refresh();
    expect(auth.unreachable).toBe(true);
    expect(auth.phase).toBe("login");
  });
});
