import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, type App } from "vue";
import { createPinia } from "pinia";
import { createI18n } from "vue-i18n";
import { createMemoryHistory, createRouter } from "vue-router";
import en from "@/i18n/en";
import fr from "@/i18n/fr";
import { pluralRules } from "@/i18n";
import DuplicatesPage from "@/pages/DuplicatesPage.vue";

/**
 * Page Doublons (P1-4g, M-36) : un fichier en trop qui est la seule copie de
 * sa face sur un appareil reste gardé, et la page le dit avant le clic — le
 * bouton ne le compte pas.
 */

function font(id: string, name: string) {
  return { id, originalFilename: name, fileSize: 1000 };
}

const MIXED = {
  items: [
    {
      family: "Mixed",
      subfamily: "Regular",
      key: "mixed\u001fregular\u001f0\u001f400\u001f5",
      keeper: font("k", "Mixed-Full.ttf"),
      redundant: [font("m", "Mixed-Mid.ttf")],
      alsoKept: [],
      protected: [
        { font: font("r", "Mixed.ttf"), devices: ["Mac-mini-de-Leo"] },
      ],
      bytesFreed: 1000,
    },
  ],
  totalGroups: 1,
  totalRedundant: 1,
  totalProtected: 2,
  protectedDevices: ["Mac-mini-de-Leo"],
  bytesFreed: 1000,
  scanned: 5,
  page: 1,
  perPage: 200,
  pages: 1,
};

const ONLY_PROTECTED = {
  ...MIXED,
  items: [],
  totalGroups: 0,
  totalRedundant: 0,
  totalProtected: 1,
  bytesFreed: 0,
};

let app: App | null = null;

afterEach(() => {
  app?.unmount();
  app = null;
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

async function render(listing: object): Promise<HTMLElement> {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(listing), { status: 200 })),
  );
  const root = document.createElement("div");
  document.body.appendChild(root);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", name: "fonts", component: { template: "<div />" } },
      { path: "/trash", name: "trash", component: { template: "<div />" } },
    ],
  });
  app = createApp(DuplicatesPage);
  app.use(createPinia());
  app.use(router);
  app.use(
    createI18n({
      legacy: false,
      locale: "fr",
      messages: { en, fr },
      pluralRules,
    }),
  );
  app.mount(root);
  for (let i = 0; i < 10; i++) await Promise.resolve();
  await new Promise((r) => setTimeout(r, 0));
  return root;
}

function resolveButton(root: HTMLElement): HTMLButtonElement | undefined {
  return [...root.querySelectorAll("button")].find((b) =>
    b.textContent?.includes("corbeille"),
  );
}

describe("DuplicatesPage : seule copie gardée (P1-4g)", () => {
  it("face mixte : le gardé est annoncé avec son appareil, le bouton ne compte que le reste", async () => {
    const root = await render(MIXED);
    const text = root.textContent ?? "";

    expect(text).toContain(
      "Gardé (seule copie sur Mac-mini-de-Leo) : Mixed.ttf",
    );
    expect(text).toContain(
      "2 fichiers en trop sont gardés : chacun est la seule copie de sa face sur Mac-mini-de-Leo",
    );
    expect(text).toContain("1 fichier en trop sur 1 face");
    expect(resolveButton(root)?.textContent?.trim()).toBe(
      "Envoyer 1 fichier à la corbeille",
    );
  });

  it("tout est gardé : « aucun doublon » à retirer, mais les gardés sont annoncés", async () => {
    const root = await render(ONLY_PROTECTED);
    const text = root.textContent ?? "";

    expect(resolveButton(root)).toBeUndefined();
    expect(text).toContain(
      "1 fichier en trop est gardé : c'est la seule copie de sa face sur Mac-mini-de-Leo",
    );
  });

  it("français : 0 est au singulier", async () => {
    const i18n = createI18n({
      legacy: false,
      locale: "fr",
      messages: { en, fr },
      pluralRules,
    });
    expect(i18n.global.t("duplicates.resolve", { n: 0 })).toBe(
      "Envoyer 0 fichier à la corbeille",
    );
    expect(i18n.global.t("duplicates.resolve", { n: 2 })).toBe(
      "Envoyer 2 fichiers à la corbeille",
    );
  });
});
