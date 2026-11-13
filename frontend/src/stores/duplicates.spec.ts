import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useDuplicatesStore } from "@/stores/duplicates";

/**
 * Page Doublons restée ouverte pendant une mise à jour qui change l'identité
 * d'une face (P1-4f) : le serveur refuse l'ancienne clé en 400. La page doit
 * recharger sa liste, pas renvoyer la même requête en boucle.
 */

function page(keys: string[]) {
  return {
    items: keys.map((key) => ({
      family: "Switz",
      subfamily: "Normal",
      key,
      keeper: {},
      redundant: [{}],
      alsoKept: [],
    })),
    totalGroups: keys.length,
    totalRedundant: keys.length,
    bytesFreed: 0,
    scanned: 10,
  };
}

const OLD_KEY = "switz\u001fnormal";
const NEW_KEY = "switz\u001fnormal\u001f0\u001f400\u001f5";

describe("duplicates store : clé périmée (P1-4f)", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("recharge la liste quand la résolution est refusée en 400", async () => {
    const responses = [
      new Response(JSON.stringify(page([OLD_KEY, "x\u001fy"]))),
      new Response(
        JSON.stringify({ detail: "Identité de face malformée dans `keys`." }),
        { status: 400 },
      ),
      new Response(JSON.stringify(page([NEW_KEY]))),
    ];
    const fetchMock = vi.fn(async () => responses.shift() as Response);
    vi.stubGlobal("fetch", fetchMock);

    const store = useDuplicatesStore();
    await store.fetchDuplicates();
    store.toggleExcluded("x\u001fy");

    await expect(store.resolve()).rejects.toThrow("malformée");

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(store.items.map((g) => g.key)).toEqual([NEW_KEY]);
  });
});
