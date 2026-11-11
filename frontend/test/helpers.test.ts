import alternatives from "./fixtures/alternatives.json";
import { describe, expect, it } from "vitest";
import {
  brisbaneInputDefaults,
  sortJourneyAlternatives,
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
    expect(statusLabel("departed")).toBe("Departed");
    expect(statusLabel("delayed", 3)).toBe("Reported delay +3 min");
    expect(statusLabel("early", -2)).toBe("Reported early −2 min");
    expect(statusLabel("scheduled")).toBe("Scheduled · No real-time data used");
    expect(statusLabel("cancelled", 3)).toBe("Cancelled");
    expect(statusLabel("boarding_skipped", 3)).toBe("Boarding stop skipped");
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

it("deduplicates timetable rows by visit ID while keeping repeated visits", () => {
  const visit = {
    trip_id: "loop",
    visit_id: "first",
    route: "T2",
    platform: "2",
    scheduled_departure_time: "2026-10-26T08:46:00Z",
  };
  const rows = normalizeDepartures([
    visit,
    { ...visit, headsign: "Duplicate with different metadata" },
    { ...visit, visit_id: "repeat" },
  ]);
  expect(rows.map((row) => row.visitId)).toEqual(["first", "repeat"]);
  expect(rows[0]?.time).toBe("2026-10-26T08:46:00Z");
});

it.each([
  ["departure", [1, 0, 3, 4, 2]],
  ["arrival", [4, 1, 0, 3, 2]],
  ["duration", [0, 3, 1, 4, 2]],
] as const)(
  "sorts planner alternatives by %s with nulls last and original ties",
  (sort, expected) => {
    const options = alternatives.alternatives;
    const fasterArrival = {
      ...options[1]!,
      planner_index: 4,
      departure: "2026-10-05T23:55:00+00:00",
      arrival: "2026-10-06T00:14:00+00:00",
      duration_mins: 70,
    };
    const ordered = sortJourneyAlternatives(
      [{ ...options[1]!, planner_index: 3 }, fasterArrival, ...options],
      sort,
    );
    expect(ordered.map(({ planner_index }) => planner_index)).toEqual(expected);
    expect(options[0]!.planner_index).toBe(1);
  },
);

it("uses the next Brisbane calendar day at UTC 14:00", () => {
  expect(brisbaneInputDefaults(new Date("2026-10-05T13:59:00Z"))).toEqual({
    date: "2026-10-05",
    time: "23:59",
  });
  expect(brisbaneInputDefaults(new Date("2026-10-05T14:00:00Z"))).toEqual({
    date: "2026-10-06",
    time: "00:00",
  });
});
