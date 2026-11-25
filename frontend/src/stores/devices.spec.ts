import { describe, expect, it } from "vitest";
import { deviceSupports } from "@/stores/devices";

/** B-32 : l'interface suit les capacités annoncées par l'agent, pas sa version. */
describe("deviceSupports", () => {
  it("faux sans capacités (agent ≤ 0.1.2)", () => {
    expect(deviceSupports({ capabilities: null }, "deactivate")).toBe(false);
    expect(deviceSupports({}, "uninstall")).toBe(false);
    expect(deviceSupports({ capabilities: [] }, "full-declaration")).toBe(
      false,
    );
  });

  it("vrai seulement pour les capacités annoncées", () => {
    const device = { capabilities: ["full-declaration", "deactivate"] };
    expect(deviceSupports(device, "deactivate")).toBe(true);
    expect(deviceSupports(device, "full-declaration")).toBe(true);
    expect(deviceSupports(device, "uninstall")).toBe(false);
  });
});
