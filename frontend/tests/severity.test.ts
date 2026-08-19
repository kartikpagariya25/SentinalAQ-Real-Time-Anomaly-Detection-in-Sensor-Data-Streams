import { describe, it, expect } from "vitest";
import { getSeverity } from "../src/lib/severity";

describe("getSeverity", () => {
  it("returns unknown for no data yet", () => {
    expect(getSeverity(null)).toBe("unknown");
  });
  it("returns normal for an unflagged reading", () => {
    expect(getSeverity({ flag: 0, spatial_label: "" })).toBe("normal");
  });
  it("returns fault for an isolated flagged reading", () => {
    expect(getSeverity({ flag: 1, spatial_label: "isolated_fault" })).toBe("fault");
  });
  it("returns event (never fault) for a spatially-corrected regional agreement", () => {
    expect(getSeverity({ flag: 0, spatial_label: "regional_agreement" })).toBe("event");
  });
});
