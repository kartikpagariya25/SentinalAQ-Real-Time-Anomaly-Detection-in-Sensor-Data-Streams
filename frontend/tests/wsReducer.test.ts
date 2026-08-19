import { describe, it, expect } from "vitest";
import { applyMessage, initialStreamState } from "../src/context/WebSocketProvider";

describe("applyMessage", () => {
  it("snapshot seeds all stations", () => {
    const state = applyMessage(initialStreamState, {
      type: "snapshot",
      stations: { "RESP-0001": null, "RESP-0002": { flag: 0, spatial_label: "" } as any },
    });
    expect(Object.keys(state.stations)).toEqual(["RESP-0001", "RESP-0002"]);
  });

  it("detection updates that station and prepends to events", () => {
    const detection = { type: "detection", station_id: "RESP-0001", flag: 1, spatial_label: "isolated_fault" } as any;
    const state = applyMessage(initialStreamState, detection);
    expect(state.stations["RESP-0001"]).toEqual(detection);
    expect(state.events[0]).toEqual(detection);
  });

  it("caps events at 200", () => {
    let state = initialStreamState;
    for (let i = 0; i < 250; i++) {
      state = applyMessage(state, { type: "detection", station_id: "X", flag: 0, spatial_label: "", timestamp: String(i) } as any);
    }
    expect(state.events.length).toBe(200);
    expect(state.events[0].timestamp).toBe("249");
  });
});
