import { describe, expect, it } from "vitest";
import { createI18n } from "vue-i18n";
import en from "@/i18n/en";
import fr from "@/i18n/fr";
import { deviceStatus, type Translate } from "@/lib/deviceStatus";

const NOW = Date.parse("2026-11-13T12:00:00Z");
const HOURS_AGO_5 = "2026-11-13T07:00:00Z";
const DAYS_AGO_2 = "2026-11-11T09:00:00Z";
const MINUTES_AGO_5 = "2026-11-13T11:55:00Z";

function translator(locale: "fr" | "en"): Translate {
  const i18n = createI18n({ legacy: false, locale, messages: { en, fr } });
  return (key, params) => i18n.global.t(key, params ?? {});
}

describe("deviceStatus (P1-3g)", () => {
  const t = translator("fr");

  it("connecté et à jour : « Connecté », en vert", () => {
    expect(
      deviceStatus(
        { lastSeenAt: MINUTES_AGO_5, syncOverdue: false },
        true,
        t,
        NOW,
      ),
    ).toEqual({ kind: "connected", text: "Connecté" });
  });

  it("connecté mais en retard : l'âge du dernier sync, en ambre", () => {
    expect(
      deviceStatus(
        { lastSeenAt: HOURS_AGO_5, syncOverdue: true },
        true,
        t,
        NOW,
      ),
    ).toEqual({ kind: "overdue", text: "Connecté — dernier sync il y a 5 h" });
  });

  it("connecté, jamais passé : en retard aussi", () => {
    expect(
      deviceStatus({ lastSeenAt: null, syncOverdue: true }, true, t, NOW),
    ).toEqual({ kind: "overdue", text: "Connecté — aucun sync enregistré" });
  });

  it("hors ligne : inchangé, même en retard", () => {
    expect(
      deviceStatus(
        { lastSeenAt: HOURS_AGO_5, syncOverdue: true },
        false,
        t,
        NOW,
      ),
    ).toEqual({ kind: "offline", text: "Vu il y a 5 h" });
  });

  it("serveur sans le champ : jamais « en retard » par défaut", () => {
    expect(deviceStatus({ lastSeenAt: HOURS_AGO_5 }, true, t, NOW).kind).toBe(
      "connected",
    );
  });

  it("anglais", () => {
    expect(
      deviceStatus(
        { lastSeenAt: HOURS_AGO_5, syncOverdue: true },
        true,
        translator("en"),
        NOW,
      ).text,
    ).toBe("Connected — last sync 5 h ago");
  });
});

describe("deviceStatus : retard de plusieurs jours (cas du mini, M-39)", () => {
  it("affiché en jours", () => {
    expect(
      deviceStatus(
        { lastSeenAt: DAYS_AGO_2, syncOverdue: true },
        true,
        translator("fr"),
        NOW,
      ).text,
    ).toBe("Connecté — dernier sync il y a 2 j");
  });
});
