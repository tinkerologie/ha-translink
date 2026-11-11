import alternatives from "./fixtures/alternatives.json";
import { describe, expect, it } from "vitest";
import {
  boardFilterOptions,
  brisbaneInputDefaults,
  filterDepartures,
  orderDepartures,
  sortJourneyAlternatives,
  available,
  modeIcon,
  normalizeDepartures,
  normalizeNoticePeriods,
  normalizeNoticeSelectors,
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
    expect(result.vehicle_tracker?.entity_id).toBe(
      "device_tracker.renamed_train",
    );
    expect(result.departures_board).toBeUndefined();
    expect(siblings(hass, "sensor.missing")).toEqual({});
    expect(stub(hass, "departures_board")).toEqual({
      entity: "sensor.renamed_stop_departures_board",
    });
  });
  it("normalizes current rows and legacy itinerary fallback, sorts missing times last", () => {
    const result = orderDepartures(
      normalizeDepartures([
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
      ]),
    );
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

it.each(["unknown", "unavailable", "missing"])(
  "resolves the renamed tracker with %s state for the card to handle",
  (state) => {
    const variant = structuredClone(hass);
    const id = "device_tracker.renamed_train";
    if (state === "missing") delete variant.states[id];
    else variant.states[id]!.state = state;
    const result = siblings(variant, "sensor.renamed_journey_itinerary");
    expect(result.vehicle_tracker?.state).toBe(
      state === "missing" ? undefined : state,
    );
  },
);

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

it("filters a shared route by direction and keeps a stale option readable", () => {
  const visits = normalizeDepartures([
    {
      visit_id: "first",
      route_id: "T:Train:T2",
      route: "T2",
      direction: "Inbound",
    },
    {
      visit_id: "second",
      route_id: "T:Train:T2",
      route: "T2",
      direction: "Outbound",
    },
    { visit_id: "third", route_id: "T:Train:T2", route: "T2" },
    { route: "77", direction: "Inbound" },
  ]);
  const routes = boardFilterOptions(visits, "route");
  expect(routes).toEqual([
    { value: "77", label: "77" },
    { value: "T:Train:T2", label: "T2" },
  ]);
  expect(
    boardFilterOptions(visits, "direction").map(({ label }) => label),
  ).toEqual(["Inbound", "Outbound"]);
  expect(filterDepartures(visits, "T:Train:T2", "Outbound")).toEqual([
    visits[1],
  ]);
  expect(filterDepartures(visits, "T:Train:T2")).toHaveLength(3);
  expect(boardFilterOptions(visits.slice(3), "route", routes[1])).toEqual(
    routes,
  );
});

it("orders by schedule or route, independently of predictions, with untimed visits last", () => {
  const visits = normalizeDepartures([
    { route: "77" },
    {
      route: "T2",
      visit_id: "first",
      scheduled_departure_time: "2026-10-26T07:46:00Z",
      expected_departure_time: "2026-10-26T08:46:00Z",
    },
    {
      route: "77",
      visit_id: "middle",
      scheduled_departure_time: "2026-10-26T07:47:00Z",
      expected_departure_time: "invalid",
    },
    {
      route: "77",
      visit_id: "last",
      scheduled_departure_time: "2026-10-26T07:48:00Z",
      expected_departure_time: null,
    },
  ]);
  expect(orderDepartures(visits).map(({ visitId }) => visitId)).toEqual([
    "first",
    "middle",
    "last",
    undefined,
  ]);
  const byRoute = orderDepartures(visits, "route");
  expect(byRoute.map(({ visitId }) => visitId)).toEqual([
    "middle",
    "last",
    "first",
    undefined,
  ]);
  expect(byRoute.map(({ expectedTime }) => expectedTime)).toEqual([
    undefined,
    undefined,
    "2026-10-26T08:46:00Z",
    undefined,
  ]);
  expect(byRoute[0]?.time).toBe("2026-10-26T07:47:00Z");
  expect(byRoute[1]?.time).toBe("2026-10-26T07:48:00Z");
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

it("keeps valid open periods and filters malformed or inverted windows", () => {
  const start = "2026-11-11T01:00:00Z";
  const end = "2026-11-12T01:00:00Z";
  expect(
    normalizeNoticePeriods([
      { start, end },
      { start, end: null },
      { start: null, end },
      { start, end: "bad" },
      { start: end, end: start },
      { start: 0 },
      {},
      [],
      null,
      "invalid",
    ]),
  ).toEqual([{ start, end }, { start }, { end }]);
});

it("keeps classified selectors with evidence for their scope and unknown selectors", () => {
  const source = [
    { scope: "network", agency_id: "QR" },
    { scope: "route", route_id: "RPSP" },
    { scope: "mode", route_type: 0, mode: "Tram" },
    { scope: "stop", stop_id: "600029" },
    { scope: "trip", trip_id: "id" },
    { scope: "unknown", unrelated: "unknown" },
    { scope: "network" },
    { scope: "stop", stop_id: 42 },
    { scope: "mode", route_type: "2" },
    { scope: "other" },
    ["network"],
    "network",
    null,
  ];
  expect(normalizeNoticeSelectors(source)).toMatchObject([
    { scope: "network", agency_id: "QR" },
    { scope: "route", route_id: "RPSP" },
    { scope: "mode", route_type: 0, mode: "Tram" },
    { scope: "stop", stop_id: "600029" },
    { scope: "trip", trip_id: "id" },
    { scope: "unknown" },
  ]);
});
