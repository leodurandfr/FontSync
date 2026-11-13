import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApp, type App } from "vue";
import { createPinia } from "pinia";
import { createI18n } from "vue-i18n";
import en from "@/i18n/en";
import fr from "@/i18n/fr";
import DevicesSection from "@/components/settings/DevicesSection.vue";
import type { Device } from "@/types/api";

/**
 * Rendu de Réglages → Appareils (P1-3g, M-39) : un appareil connecté dont
 * l'agent ne passe plus doit se voir, au lieu d'un « Connecté » rassurant.
 */

const HOUR = 3_600_000;

function device(overrides: Partial<Device>): Device {
  return {
    id: crypto.randomUUID(),
    name: "Mac",
    hostname: "mac.local",
    os: "macos",
    osVersion: null,
    agentVersion: "0.1.1",
    lastSeenAt: new Date(Date.now() - 5 * 60_000).toISOString(),
    fontDirectories: null,
    autoPull: false,
    autoPush: true,
    propagateDeletions: false,
    createdAt: "2026-10-01T00:00:00Z",
    isOnline: true,
    syncOverdue: false,
    ...overrides,
  };
}

let app: App | null = null;

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setInterval", "clearInterval", "setTimeout", "Date"],
  });
  vi.setSystemTime(new Date("2026-11-13T12:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
  app?.unmount();
  app = null;
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

let served: Device[] = [];

async function flush(): Promise<void> {
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

async function render(devices: Device[]): Promise<HTMLElement> {
  served = devices;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(served), { status: 200 })),
  );
  const root = document.createElement("div");
  document.body.appendChild(root);
  app = createApp(DevicesSection);
  app.use(createPinia());
  app.use(createI18n({ legacy: false, locale: "fr", messages: { en, fr } }));
  app.mount(root);
  for (let i = 0; i < 5; i++) await vi.advanceTimersByTimeAsync(0);
  return root;
}

function dot(root: HTMLElement, name: string): HTMLElement {
  const line = statusLine(root, name);
  const card = line.closest(".rounded-lg") as HTMLElement;
  return card.querySelector("span.rounded-full") as HTMLElement;
}

function statusLine(root: HTMLElement, name: string): HTMLElement {
  const title = [...root.querySelectorAll("p")].find(
    (p) => p.textContent?.trim() === name,
  );
  const card = title?.closest(".rounded-lg") as HTMLElement | null;
  const line = card?.querySelector("p.text-xs") as HTMLElement | null;
  if (!line) throw new Error(`ligne d'état introuvable pour ${name}`);
  return line;
}

describe("DevicesSection : ligne d'état (P1-3g)", () => {
  it("connecté et en retard : âge du dernier sync, en ambre", async () => {
    const root = await render([
      device({
        name: "Mac mini",
        syncOverdue: true,
        lastSeenAt: new Date(Date.now() - 50 * HOUR).toISOString(),
      }),
    ]);

    const line = statusLine(root, "Mac mini");
    expect(line.textContent?.trim()).toBe("Connecté — dernier sync il y a 2 j");
    expect(line.className).toContain("text-amber-600");
    expect(dot(root, "Mac mini").className).toContain("bg-amber-500");
  });

  it("connecté et à jour : « Connecté », en vert", async () => {
    const root = await render([device({ name: "MacBook" })]);

    const line = statusLine(root, "MacBook");
    expect(line.textContent?.trim()).toBe("Connecté");
    expect(line.className).toContain("text-green-600");
    expect(dot(root, "MacBook").className).toContain("bg-green-500");
  });

  it("hors ligne : « Vu il y a… », inchangé même en retard", async () => {
    const root = await render([
      device({
        name: "Ancien Mac",
        isOnline: false,
        syncOverdue: true,
        lastSeenAt: new Date(Date.now() - 5 * HOUR).toISOString(),
      }),
    ]);

    const line = statusLine(root, "Ancien Mac");
    expect(line.textContent?.trim()).toBe("Vu il y a 5 h");
    expect(line.className).toContain("text-muted-foreground");
  });

  it("page ouverte : le sync qui reprend lève l'alerte sans recharger", async () => {
    const id = crypto.randomUUID();
    const stalled = new Date(Date.now() - 9 * HOUR).toISOString();
    const root = await render([
      device({ id, name: "MacBook", syncOverdue: true, lastSeenAt: stalled }),
    ]);
    expect(statusLine(root, "MacBook").className).toContain("text-amber-600");

    // Réveil : son sync passe, le serveur ne le dit plus en retard.
    served = [
      device({ id, name: "MacBook", lastSeenAt: new Date().toISOString() }),
    ];
    await vi.advanceTimersByTimeAsync(30_000);
    await flush();

    const line = statusLine(root, "MacBook");
    expect(line.textContent?.trim()).toBe("Connecté");
    expect(line.className).toContain("text-green-600");
    expect(
      root.querySelector('[data-slot="skeleton"], .animate-pulse'),
    ).toBeNull();
  });

  it("page ouverte : un sync qui casse finit par se voir", async () => {
    const id = crypto.randomUUID();
    const root = await render([device({ id, name: "Mac mini" })]);
    expect(statusLine(root, "Mac mini").textContent?.trim()).toBe("Connecté");

    served = [
      device({
        id,
        name: "Mac mini",
        syncOverdue: true,
        lastSeenAt: new Date(Date.now() - 31 * 60_000).toISOString(),
      }),
    ];
    await vi.advanceTimersByTimeAsync(30_000);
    await flush();

    expect(statusLine(root, "Mac mini").textContent?.trim()).toBe(
      "Connecté — dernier sync il y a 31 min",
    );
  });
});

describe("DevicesSection : retrait d'un appareil (P1-6e)", () => {
  function deleteButton(root: HTMLElement, name: string): HTMLButtonElement {
    const card = statusLine(root, name).closest(".rounded-lg") as HTMLElement;
    const button = card.querySelector(
      'button[aria-label="Retirer l\'appareil"]',
    ) as HTMLButtonElement | null;
    if (!button) throw new Error("bouton de retrait introuvable");
    return button;
  }

  it("demande confirmation dans un dialogue de l'app, jamais par window.confirm", async () => {
    // Dans la WebView de l'app Mac, window.confirm répondait false en silence :
    // le bouton ne faisait rien.
    const confirmSpy = vi.fn(() => true);
    vi.stubGlobal("confirm", confirmSpy);
    const id = crypto.randomUUID();
    const root = await render([device({ id, name: "Mac mini" })]);

    deleteButton(root, "Mac mini").click();
    await flush();
    await vi.advanceTimersByTimeAsync(0);

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain("Retirer « Mac mini » ?");
    expect(document.body.textContent).toContain("Rien n'est effacé");

    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    const confirmButton = [...document.body.querySelectorAll("button")].find(
      (b) => b.textContent?.trim() === "Retirer l'appareil",
    );
    expect(confirmButton).toBeDefined();
    confirmButton!.click();
    await flush();
    await vi.advanceTimersByTimeAsync(0);

    const deletes = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "DELETE",
    );
    expect(deletes.map(([url]) => String(url))).toEqual([`/api/devices/${id}`]);
  });

  async function settle(): Promise<void> {
    await flush();
    for (let i = 0; i < 3; i++) await vi.advanceTimersByTimeAsync(0);
  }

  function dialog(): HTMLElement | null {
    return document.body.querySelector('[role="dialog"]');
  }

  function button(text: string): HTMLButtonElement {
    const found = [...document.body.querySelectorAll("button")].find(
      (b) => b.textContent?.trim() === text,
    );
    if (!found) throw new Error(`bouton « ${text} » introuvable`);
    return found;
  }

  function deletes(): string[] {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    return fetchMock.mock.calls
      .filter(
        ([, init]) => (init as RequestInit | undefined)?.method === "DELETE",
      )
      .map(([url]) => String(url));
  }

  it("annuler ferme le dialogue sans rien retirer", async () => {
    const root = await render([device({ name: "MacBook" })]);

    deleteButton(root, "MacBook").click();
    await settle();
    expect(dialog()).not.toBeNull();
    button("Annuler").click();
    await settle();

    expect(dialog()).toBeNull();
    expect(deletes()).toEqual([]);
  });

  it("Échap ferme le dialogue sans rien retirer, et il se rouvre", async () => {
    const root = await render([device({ name: "MacBook" })]);

    deleteButton(root, "MacBook").click();
    await settle();
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    );
    await settle();
    expect(dialog()).toBeNull();
    expect(deletes()).toEqual([]);

    deleteButton(root, "MacBook").click();
    await settle();
    expect(dialog()).not.toBeNull();
  });

  it("un double clic sur « Retirer » n'envoie qu'une suppression", async () => {
    const id = crypto.randomUUID();
    const root = await render([device({ id, name: "Mac mini" })]);

    deleteButton(root, "Mac mini").click();
    await settle();
    const remove = button("Retirer l'appareil");
    remove.click();
    remove.click();
    await settle();

    expect(deletes()).toEqual([`/api/devices/${id}`]);
  });

  it("le titre garde le nom pendant l'animation de fermeture", async () => {
    // jsdom n'anime rien : on simule l'animation de sortie de reka (Presence
    // garde le contenu monté tant que `animationName` n'est pas « none »).
    const real = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation(
      (el: Element, pseudo?: string | null) => {
        const style = real(el, pseudo);
        const slot = el.getAttribute?.("data-slot");
        if (slot !== "dialog-content" && slot !== "dialog-overlay")
          return style;
        const closed = el.getAttribute("data-state") === "closed";
        return new Proxy(style, {
          get: (target, key) =>
            key === "animationName"
              ? closed
                ? "exit"
                : "enter"
              : key === "display"
                ? "block"
                : Reflect.get(target, key),
        });
      },
    );
    const root = await render([device({ name: "Mac mini" })]);

    deleteButton(root, "Mac mini").click();
    await settle();
    button("Annuler").click();
    await settle();

    const closing = dialog();
    expect(closing?.getAttribute("data-state")).toBe("closed");
    expect(closing?.textContent).toContain("Retirer « Mac mini » ?");
    vi.restoreAllMocks();
  });
});
