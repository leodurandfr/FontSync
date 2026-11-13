import { describe, expect, it } from "vitest";
import { backupWarning } from "@/composables/useBackupHealth";
import type { BackupHealth } from "@/types/api";

function health(overrides: Partial<BackupHealth> = {}): BackupHealth {
  return {
    enabled: true,
    lastSnapshotAt: "2026-11-13T09:00:00Z",
    lastSnapshotBytes: 35_303_424,
    lastErrorAt: null,
    lastError: null,
    lastMirrorAt: "2026-11-13T09:00:05Z",
    mirrorCopied: 3,
    mirrorRepaired: 0,
    mirrorFailed: 0,
    stale: false,
    ...overrides,
  };
}

describe("backupWarning (P1-2b)", () => {
  it("ne signale rien quand tout va bien", () => {
    expect(backupWarning(health())).toBeNull();
  });

  it("ne signale rien tant que l'état n'est pas connu", () => {
    expect(backupWarning(null)).toBeNull();
  });

  it("ne signale rien quand les sauvegardes sont désactivées", () => {
    expect(
      backupWarning(
        health({
          enabled: false,
          stale: true,
          lastSnapshotAt: null,
          lastError: "x",
          mirrorFailed: 1,
        }),
      ),
    ).toBeNull();
  });

  it("signale une sauvegarde en retard (plus de 36 h ou aucune)", () => {
    expect(backupWarning(health({ stale: true }))).toBe("stale");
  });

  it("signale la dernière erreur", () => {
    expect(
      backupWarning(
        health({
          lastError: "OperationalError: unable to open database file",
          lastErrorAt: "2026-11-13T09:00:00Z",
        }),
      ),
    ).toBe("error");
  });

  it("signale un miroir incomplet", () => {
    expect(backupWarning(health({ mirrorFailed: 2 }))).toBe("mirror");
  });

  it("donne la priorité au retard sur l'erreur et le miroir", () => {
    expect(
      backupWarning(health({ stale: true, lastError: "x", mirrorFailed: 1 })),
    ).toBe("stale");
  });

  it("donne la priorité à l'erreur sur le miroir", () => {
    expect(backupWarning(health({ lastError: "x", mirrorFailed: 1 }))).toBe(
      "error",
    );
  });
});
