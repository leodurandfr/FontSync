import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { dispatch } from "@/composables/useWebSocket";
import { useFontsStore } from "@/stores/fonts";
import { useFamiliesStore } from "@/stores/families";
import { useTrashStore } from "@/stores/trash";
import type { Font, WsMessage } from "@/types/api";

/**
 * Dispatch des messages temps réel (P1-7c, B-44) : `fonts.deleted` retire
 * toute une quarantaine d'un coup et recharge les familles déjà affichées.
 */

describe("useWebSocket — dispatch", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("removes all quarantined fonts from one fonts.deleted message", () => {
    const fonts = useFontsStore();
    fonts.fonts = ["a", "b", "c"].map((id) => ({ id }) as unknown as Font);
    fonts.total = 3;
    const removeFonts = vi.spyOn(fonts, "removeFonts");

    dispatch({ type: "fonts.deleted", data: { ids: ["a", "c"] } } as WsMessage);

    expect(removeFonts).toHaveBeenCalledTimes(1);
    expect(fonts.fonts.map((f) => f.id)).toEqual(["b"]);
    expect(fonts.total).toBe(1);
  });

  it("reloads the families only when they are displayed", () => {
    const families = useFamiliesStore();
    const fetchFamilies = vi
      .spyOn(families, "fetchFamilies")
      .mockResolvedValue(undefined);

    dispatch({ type: "fonts.deleted", data: { ids: ["a"] } } as WsMessage);
    expect(fetchFamilies).not.toHaveBeenCalled();

    families.initialized = true;
    dispatch({ type: "fonts.deleted", data: { ids: ["a"] } } as WsMessage);
    expect(fetchFamilies).toHaveBeenCalledTimes(1);
  });

  it("refreshes the trash only when it is displayed", () => {
    const trash = useTrashStore();
    const fetchTrash = vi
      .spyOn(trash, "fetchTrash")
      .mockResolvedValue(undefined);

    dispatch({ type: "fonts.deleted", data: { ids: ["a"] } } as WsMessage);
    expect(fetchTrash).not.toHaveBeenCalled();

    trash.initialized = true;
    dispatch({ type: "fonts.deleted", data: { ids: ["a"] } } as WsMessage);
    expect(fetchTrash).toHaveBeenCalledTimes(1);
  });

  it("ignores a malformed fonts.deleted payload", () => {
    const fonts = useFontsStore();
    fonts.fonts = [{ id: "a" } as unknown as Font];
    fonts.total = 1;
    dispatch({ type: "fonts.deleted", data: { ids: "a" } } as WsMessage);
    dispatch({ type: "fonts.deleted", data: { ids: ["a", 3] } } as WsMessage);
    expect(fonts.fonts.map((f) => f.id)).toEqual(["a"]);
  });

  it("still handles the single font.deleted message", () => {
    const fonts = useFontsStore();
    fonts.fonts = [{ id: "a" } as unknown as Font];
    fonts.total = 1;
    dispatch({ type: "font.deleted", data: { id: "a" } } as WsMessage);
    expect(fonts.fonts).toEqual([]);
  });
});
