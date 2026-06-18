import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useAuthStore } from "@/stores/auth";

describe("auth store (P1.4)", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it("demande le token quand rien n'est mémorisé", () => {
    const auth = useAuthStore();
    expect(auth.token).toBeNull();
    expect(auth.needsToken).toBe(true);
  });

  it("relit un token déjà mémorisé sans redemander la saisie", () => {
    localStorage.setItem("fontsync_token", "abc");
    setActivePinia(createPinia()); // store recréé après avoir amorcé le storage
    const auth = useAuthStore();
    expect(auth.token).toBe("abc");
    expect(auth.needsToken).toBe(false);
  });

  it("setToken trim, persiste et ferme l'écran de saisie", () => {
    const auth = useAuthStore();
    auth.setToken("  secret  ");
    expect(auth.token).toBe("secret");
    expect(localStorage.getItem("fontsync_token")).toBe("secret");
    expect(auth.needsToken).toBe(false);
  });

  it("clearToken efface le token et réaffiche la saisie", () => {
    const auth = useAuthStore();
    auth.setToken("secret");
    auth.clearToken();
    expect(auth.token).toBeNull();
    expect(localStorage.getItem("fontsync_token")).toBeNull();
    expect(auth.needsToken).toBe(true);
  });

  it("markUnauthorized réaffiche la saisie sans jeter la valeur courante", () => {
    const auth = useAuthStore();
    auth.setToken("secret");
    auth.markUnauthorized();
    expect(auth.needsToken).toBe(true);
    expect(auth.token).toBe("secret");
  });
});
