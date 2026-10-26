import { describe, expect, it } from "vitest";
import {
  available,
  modeIcon,
  normalizeDepartures,
  number,
  routeColors,
  rows,
  siblings,
  statusLabel,
  stub,
  text,
  time,
} from "../src/helpers";
import fixture from "./fixtures/hass.json";
import type { HomeAssistant } from "../src/types";
const hass = fixture as HomeAssistant;
describe("entity and departure contracts", () => {
  it("resolves renamed IDs only within the anchor device", () => {
    const result = siblings(hass, "sensor.renamed_journey_itinerary");
    expect(result.next_departure?.entity_id).toBe(
      "sensor.renamed_journey_next_departure",
    );
    expect(result.departures_board).toBeUndefined();
    expect(siblings(hass, "sensor.missing")).toEqual({});
    expect(stub(hass, "departures_board")).toEqual({
      entity: "sensor.renamed_stop_departures_board",
    });
  });
  it("normalizes current rows and legacy itinerary fallback, sorts missing times last", () => {
    const result = normalizeDepartures([
      {
        route: "Late",
        departure_time: "2026-10-26T08:00:00Z",
        vehicle: "Train",
      },
      null,
      { route: "Unknown" },
      {
        route: "Early",
        departureTimeUtc: "2026-10-26T07:00:00Z",
        travelMode: "Walk",
        originPlatform: "1",
      },
    ]);
    expect(result.map((r) => r.route)).toEqual(["Early", "Late", "Unknown"]);
    expect(result[0]).toMatchObject({ vehicle: "Walk", platform: "1" });
  });
  it("distinguishes missing and explicit values without fake live status", () => {
    expect(statusLabel("on_time", 0)).toBe("No delay reported");
    expect(statusLabel("departed")).toBe("Departed (scheduled)");
    expect(statusLabel("delayed", 3)).toBe("Reported delay +3 min");
    expect(statusLabel("no_service")).toBe("No services found");
    expect(
      available({ entity_id: "sensor.x", state: "unknown", attributes: {} }),
    ).toBe(false);
    expect(text("$undefined")).toBeUndefined();
    expect(number(null)).toBeUndefined();
    expect(number("0")).toBe(0);
    expect(rows([[], null, {}, 2])).toEqual([{}]);
  });
});

it("falls back safely for invalid locale and timezone preferences", () => {
  expect(
    time("2026-10-26T07:46:00Z", {
      config: { time_zone: "Invalid/Zone" },
      locale: { language: "invalid_locale", time_format: "24" },
      states: {},
    }),
  ).toBe("17:46");
});

it.each([
  ["Walk", "mdi:walk"],
  ["Train", "mdi:train"],
  ["Tram", "mdi:tram"],
  ["Ferry", "mdi:ferry"],
  ["Boat", "mdi:ferry"],
  ["Bus", "mdi:bus"],
  [undefined, "mdi:bus"],
])("uses the correct mode icon for %s", (mode, icon) => {
  expect(modeIcon(mode)).toBe(icon);
});
describe("formatting", () => {
  it("honors 12/24 hour and server timezone preferences", () => {
    const iso = "2026-10-26T07:46:00Z";
    expect(time(iso, hass)).toMatch(/5:46/);
    expect(
      time(iso, { ...hass, locale: { ...hass.locale, time_format: "24" } }),
    ).toBe("17:46");
    expect(
      time(iso, {
        ...hass,
        config: { time_zone: "UTC" },
        locale: { time_format: "24" },
      }),
    ).toBe("07:46");
    expect(time("invalid", hass)).toBe("—");
  });
  it("uses safe theme fallbacks and contrasting route text", () => {
    expect(routeColors("#6cc6e9").foreground).toBe("#000000");
    expect(routeColors("#111111").foreground).toBe("#ffffff");
    expect(routeColors("url(https://example.com)").background).toContain(
      "var(",
    );
  });
});

it("collapses duplicate planner departures but preserves different trip identities", () => {
  const row = {
    departure_time: "2026-10-26T08:46:00Z",
    route: "T2 Springfield Central",
    vehicle: "Train",
    headsign: "Springfield Central",
    platform: "2",
  };
  expect(normalizeDepartures([row, { ...row }])).toHaveLength(1);
  expect(
    normalizeDepartures([
      { ...row, trip_id: "A" },
      { ...row, trip_id: "B" },
    ]),
  ).toHaveLength(2);
  expect(normalizeDepartures([row, { ...row, platform: "1" }])).toHaveLength(2);
});
