import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useFontsStore } from "@/stores/fonts";
import type { Font } from "@/types/api";

/**
 * Quarantaine notifiée en un seul message `fonts.deleted` (P1-7c, B-44) :
 * le store retire toutes les polices en une passe.
 */

function font(id: string): Font {
  return { id } as unknown as Font;
}

describe("fonts store — removeFonts", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("removes every listed font in one pass and updates the total", () => {
    const store = useFontsStore();
    store.fonts = [font("a"), font("b"), font("c")];
    store.total = 10;

    // "zz" n'est pas dans la liste (hors filtres, ou déjà retiré) : il ne
    // compte pas ; les doublons non plus.
    store.removeFonts(["a", "b", "zz", "a"]);

    expect(store.fonts.map((f) => f.id)).toEqual(["c"]);
    expect(store.total).toBe(8);
  });

  it("does not decrement twice a font already removed", () => {
    const store = useFontsStore();
    store.fonts = [font("a"), font("b")];
    store.total = 2;
    store.removeFont("a");
    store.removeFonts(["a"]);
    expect(store.fonts.map((f) => f.id)).toEqual(["b"]);
    expect(store.total).toBe(1);
  });

  it("never lets the total go below zero", () => {
    const store = useFontsStore();
    store.fonts = [font("a")];
    store.total = 1;
    store.removeFonts(["a", "b", "c"]);
    expect(store.fonts).toEqual([]);
    expect(store.total).toBe(0);
  });

  it("does nothing for an empty list", () => {
    const store = useFontsStore();
    store.fonts = [font("a")];
    store.total = 4;
    store.removeFonts([]);
    expect(store.fonts.map((f) => f.id)).toEqual(["a"]);
    expect(store.total).toBe(4);
  });
});
