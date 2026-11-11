import { afterEach, describe, expect, it, vi } from "vitest";
import "../src/index";
import { AlertsCard, DeparturesCard, JourneyCard } from "../src/cards";
import alternatives from "./fixtures/alternatives.json";
import fixture from "./fixtures/hass.json";
import type {
  CardConfig,
  HomeAssistant,
  JourneyAlternatives,
} from "../src/types";
afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function journey(
  hass?: HomeAssistant,
  entity = "sensor.renamed_journey_itinerary",
) {
  const card = document.createElement("translink-journey-card") as JourneyCard;
  card.setConfig({ type: "custom:translink-journey-card", entity });
  card.hass = hass;
  document.body.append(card);
  await card.updateComplete;
  return card;
}
const stopBoard = "sensor.renamed_stop_departures_board";

async function board(hass: HomeAssistant, config: Partial<CardConfig> = {}) {
  const card = document.createElement(
    "translink-departures-card",
  ) as DeparturesCard;
  card.setConfig({
    type: "custom:translink-departures-card",
    entity: stopBoard,
    ...config,
  });
  card.hass = hass;
  document.body.append(card);
  await card.updateComplete;
  return card;
}

const vehicleTracker = "device_tracker.renamed_train";
const journeyDisruptions = "sensor.renamed_journey_disruptions";
function emptyJourney(
  status = "no_service",
  disruptionCount = "1",
  disruptionTitle: string | null = "Line closure",
): HomeAssistant {
  const hass = structuredClone(fixture) as HomeAssistant;
  delete hass.states[vehicleTracker];
  const itinerary = "sensor.renamed_journey_itinerary";
  const statusEntity = "sensor.renamed_journey_status";
  hass.states[itinerary] = {
    ...hass.states[itinerary]!,
    attributes: { ...hass.states[itinerary]!.attributes, legs: [] },
  };
  hass.states[statusEntity] = { ...hass.states[statusEntity]!, state: status };
  hass.states[journeyDisruptions] = {
    ...hass.states[journeyDisruptions]!,
    state: disruptionCount,
    attributes:
      disruptionTitle === null ? {} : { latest_title: disruptionTitle },
  };
  return hass;
}
describe("card states and interactions", () => {
  it("registers four cards with native editor schemas", () => {
    expect(window.customCards).toHaveLength(4);
    expect(JourneyCard.getConfigForm().schema[0]?.selector).toMatchObject({
      entity: { filter: { integration: "translink" } },
    });
    expect(DeparturesCard.getConfigForm().schema).toEqual(
      expect.arrayContaining([
        { name: "show_arrivals", selector: { boolean: {} } },
        { name: "show_filters", selector: { boolean: {} } },
      ]),
    );
    expect(JourneyCard.getStubConfig(fixture)).toEqual({
      entity: "sensor.renamed_journey_itinerary",
    });
  });
  it("renders scheduled journeys and toggles details, without fabricated tracking", async () => {
    const hass = structuredClone(fixture) as HomeAssistant;
    delete hass.states[vehicleTracker];
    const card = await journey(hass);
    expect(card.shadowRoot?.textContent).toContain("Scheduled");
    expect(card.shadowRoot?.textContent).not.toContain("Live");
    const button =
      card.shadowRoot!.querySelector<HTMLButtonElement>(".disclosure")!;
    expect(button.getAttribute("aria-expanded")).toBe("false");
    button.click();
    await card.updateComplete;
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(card.shadowRoot!.querySelectorAll(".leg").length).toBeGreaterThan(0);
    let entityId = "";
    card.addEventListener("hass-more-info", (event) => {
      entityId = (event as CustomEvent).detail.entityId;
    });
    card.shadowRoot!.querySelector<HTMLButtonElement>(".icon-button")!.click();
    expect(entityId).toBe("sensor.renamed_journey_itinerary");
  });
  it("keeps loading, missing, unavailable and no-service distinct", async () => {
    expect((await journey()).shadowRoot!.textContent).toContain("Loading");
    expect(
      (await journey(fixture, "sensor.absent")).shadowRoot!.textContent,
    ).toContain("Entity not found");
    const unavailable = structuredClone(fixture);
    unavailable.states["sensor.renamed_journey_itinerary"].state =
      "unavailable";
    expect((await journey(unavailable)).shadowRoot!.textContent).toContain(
      "unavailable",
    );
    const root = (await journey(emptyJourney())).shadowRoot!;
    expect(root.querySelector('[role="status"]')?.textContent).toBe(
      "No services found",
    );
    expect(root.querySelector(".alert-strip")?.textContent).toMatch(
      /1 service alert ·\s+Line closure/,
    );
  });
  it("honors the disruption display option when no services are found", async () => {
    const card = await journey(emptyJourney());
    card.setConfig({
      type: "custom:translink-journey-card",
      entity: "sensor.renamed_journey_itinerary",
      show_disruptions: false,
    });
    await card.updateComplete;
    expect(card.shadowRoot!.textContent).toContain("No services found");
    expect(card.shadowRoot!.querySelector(".alert-strip")).toBeNull();
  });
  it.each(["unavailable", "0"])(
    "hides the no-service disruption strip for a count of %s",
    async (count) => {
      const card = await journey(emptyJourney("no_service", count));
      expect(card.shadowRoot!.textContent).toContain("No services found");
      expect(card.shadowRoot!.querySelector(".alert-strip")).toBeNull();
    },
  );
  it("shows disruption information for empty legs even with a scheduled status", async () => {
    const card = await journey(emptyJourney("scheduled", "1", null));
    expect(card.shadowRoot!.textContent).toContain("No services found");
    expect(
      card.shadowRoot!.querySelector(".alert-strip")?.textContent,
    ).toContain("Check service information");
  });
  it("escapes upstream notice titles in the no-service disruption strip", async () => {
    const title = "<img src=x onerror=alert(1)>";
    const card = await journey(emptyJourney("no_service", "1", title));
    const strip = card.shadowRoot!.querySelector(".alert-strip")!;
    expect(strip.textContent).toContain(title);
    expect(strip.querySelector("img")).toBeNull();
  });
  it("shows predicted arrival alongside the schedule", async () => {
    const hass = structuredClone(fixture) as HomeAssistant;
    hass.states[
      "sensor.renamed_journey_arrival_time"
    ]!.attributes.predicted_time = "2026-10-26T09:00:00Z";
    const card = await journey(hass);
    const destination = card.shadowRoot!.querySelector(".destination")!;
    expect(destination.textContent).toContain("Arrival · Scheduled");
    expect(destination.textContent).toContain("Predicted 7:00 pm");
  });
  it("escapes upstream descriptions and validates configuration", async () => {
    const card = document.createElement("translink-alerts-card") as AlertsCard;
    const hass = structuredClone(fixture) as HomeAssistant;
    hass.states["sensor.renamed_journey_disruptions"]!.attributes.disruptions =
      [
        {
          title: "<script>alert(1)</script>",
          description: "<img src=x onerror=alert(1)>",
        },
      ];
    card.setConfig({
      type: "custom:translink-alerts-card",
      entity: "sensor.renamed_journey_disruptions",
    });
    card.hass = hass;
    document.body.append(card);
    await card.updateComplete;
    expect(card.shadowRoot!.querySelector("script,img")).toBeNull();
    expect(card.shadowRoot!.textContent).toContain("<script>");
    expect(() =>
      card.setConfig({ type: "custom:x", max_alerts: 21 }),
    ).toThrow();
  });
});

it("shows a signed next-service delay and omits it when unknown", async () => {
  const card = document.createElement(
    "translink-departures-card",
  ) as DeparturesCard;
  card.setConfig({
    type: "custom:translink-departures-card",
    entity: "sensor.renamed_stop_departures_board",
  });
  const hass = structuredClone(fixture) as HomeAssistant;
  hass.states["sensor.renamed_stop_delay"]!.state = "-2";
  card.hass = hass;
  document.body.append(card);
  await card.updateComplete;
  expect(card.shadowRoot!.querySelector(".alert-strip")?.textContent).toContain(
    "Reported early −2 min",
  );
  const withoutDelay = structuredClone(hass);
  withoutDelay.states["sensor.renamed_stop_delay"]!.state = "unknown";
  card.hass = withoutDelay;
  await card.updateComplete;
  expect(card.shadowRoot!.querySelector(".alert-strip")).toBeNull();
});

it("shows supplied calling times and keeps predictions separate", async () => {
  const card = await journey(fixture);
  card.shadowRoot!.querySelector<HTMLButtonElement>(".disclosure")!.click();
  await card.updateComplete;
  expect(card.shadowRoot!.querySelectorAll(".call")).toHaveLength(20);
  expect(card.shadowRoot!.textContent).toContain("Rothwell station");
  expect(card.shadowRoot!.textContent).toContain("Scheduled calling times");
  expect(card.shadowRoot!.textContent).not.toContain("Predicted");
  const hass = structuredClone(fixture) as HomeAssistant;
  const leg = (
    hass.states["sensor.renamed_journey_itinerary"]!.attributes.legs as Record<
      string,
      unknown
    >[]
  )[1]!;
  leg.callingStopsSource = "realtime_partial";
  leg.callingStops = [
    {
      stopId: "600633",
      name: "Kippa-Ring",
      scheduledTimeUtc: null,
      realtime: {
        departureTimeUtc: "2026-10-26T07:47:00Z",
        departureDelaySeconds: 60,
      },
    },
  ];
  card.hass = hass;
  await card.updateComplete;
  expect(card.shadowRoot!.textContent).toContain("Partial real-time list");
  expect(card.shadowRoot!.textContent).toContain("Predicted");
  expect(card.shadowRoot!.querySelectorAll(".call")).toHaveLength(1);
  leg.callingStopsSource = "unavailable";
  card.hass = {
    ...hass,
    states: {
      ...hass.states,
      "sensor.renamed_journey_itinerary": {
        ...hass.states["sensor.renamed_journey_itinerary"]!,
      },
    },
  };
  await card.updateComplete;
  expect(card.shadowRoot!.querySelector(".stop-details")).toBeNull();
});

it("suggests only matching entities and tolerates a repeated resource load", async () => {
  const registered = window.customCards!.slice();
  for (const [tag, entity] of [
    ["translink-journey-card", "sensor.renamed_journey_itinerary"],
    ["translink-departures-card", "sensor.renamed_stop_departures_board"],
    ["translink-alerts-card", "sensor.renamed_journey_disruptions"],
  ] as const) {
    const metadata = registered.find((entry) => entry.type === tag)!;
    expect(metadata.getEntitySuggestion!(fixture, entity)).toEqual({
      config: { type: `custom:${tag}`, entity },
    });
    expect(metadata.getEntitySuggestion!(fixture, "sensor.missing")).toBeNull();
    const foreign = structuredClone(fixture);
    foreign.entities[entity].platform = "other";
    expect(metadata.getEntitySuggestion!(foreign, entity)).toBeNull();
  }
  expect(
    registered[0]!.getEntitySuggestion!(
      fixture,
      "sensor.renamed_stop_departures_board",
    ),
  ).toBeNull();
  const path = "../src/index.ts?registration-check";
  await import(path);
  expect(window.customCards).toEqual(registered);
  expect(customElements.get("translink-journey-card")).toBe(JourneyCard);
});

it.each([
  ["translink-journey-card", "sensor.renamed_journey_itinerary"],
  ["translink-departures-card", "sensor.renamed_stop_departures_board"],
  ["translink-alerts-card", "sensor.renamed_journey_disruptions"],
])("explains configuration and registry states for %s", async (tag, entity) => {
  const card = document.createElement(tag) as JourneyCard;
  card.setConfig({ type: `custom:${tag}` });
  document.body.append(card);
  await card.updateComplete;
  expect(card.shadowRoot!.textContent).toContain("Choose a Translink entity");
  card.setConfig({ type: `custom:${tag}`, entity });
  card.hass = { states: fixture.states };
  await card.updateComplete;
  expect(card.shadowRoot!.textContent).toContain("Loading");
  const foreign = structuredClone(fixture) as HomeAssistant;
  foreign.entities![entity]!.platform = "other";
  card.hass = foreign;
  await card.updateComplete;
  expect(card.shadowRoot!.textContent).toContain(
    "Select the matching Translink entity",
  );
  const unknown = structuredClone(fixture) as HomeAssistant;
  unknown.states[entity]!.state = "unknown";
  card.hass = unknown;
  await card.updateComplete;
  expect(card.shadowRoot!.textContent).toContain("unavailable");
});

it.each([
  null,
  {},
  { type: 2 },
  { entity: 1 },
  { title: false },
  ...["show_fare", "legs_expanded", "show_disruptions", "show_platform"].map(
    (key) => ({ [key]: "true" }),
  ),
  { show_arrivals: "true" },
  { show_filters: "true" },
  ...["max_departures", "max_alerts"].flatMap((key) =>
    [0, 21, 1.5, "2"].map((value) => ({ [key]: value })),
  ),
])("rejects invalid editor configuration %j", (invalid) => {
  const card = document.createElement("translink-journey-card") as JourneyCard;
  const config =
    invalid === null || Object.keys(invalid).length === 0
      ? invalid
      : { type: "custom:translink-journey-card", ...invalid };
  // YAML values can bypass the TypeScript configuration contract.
  expect(() => card.setConfig(config as unknown as CardConfig)).toThrow();
});

it("limits departures, can hide platforms, and explains an empty board", async () => {
  const hass = structuredClone(fixture) as HomeAssistant;
  const state = hass.states["sensor.renamed_stop_departures_board"]!;
  state.attributes.departures = [1, 2, 3].map((platform) => ({
    route: "T2",
    platform: String(platform),
    departure_time: "2026-10-26T07:46:00Z",
  }));
  const card = document.createElement(
    "translink-departures-card",
  ) as DeparturesCard;
  const config = {
    type: "custom:translink-departures-card",
    entity: state.entity_id,
    max_departures: 1,
  };
  card.setConfig(config);
  card.hass = hass;
  document.body.append(card);
  await card.updateComplete;
  expect(card.shadowRoot!.querySelectorAll(".departure")).toHaveLength(1);
  expect(card.shadowRoot!.textContent).toContain("Showing 1 of 3");
  expect(card.shadowRoot!.textContent).toContain("Platform 1");
  card.setConfig({ ...config, show_platform: false });
  await card.updateComplete;
  expect(card.shadowRoot!.textContent).not.toContain("Platform 1");
  const empty = structuredClone(hass);
  empty.states[state.entity_id]!.attributes.departures = [];
  const alerts = empty.states["sensor.renamed_stop_disruptions"]!;
  alerts.state = "2";
  alerts.attributes.latest_title = "Lift <img> maintenance";
  card.hass = empty;
  await card.updateComplete;
  expect(card.shadowRoot!.textContent).toContain("No services found");
  expect(card.shadowRoot!.textContent).toMatch(
    /2 service alerts\s*·\s*Lift <img> maintenance/,
  );
  expect(card.shadowRoot!.querySelector("img")).toBeNull();
});

it("shows drop-off visits only when the opt-in Arrivals view is selected", async () => {
  const hass = structuredClone(fixture) as HomeAssistant;
  hass.states[stopBoard]!.attributes.arrivals = [
    {
      route: "T2",
      visit_id: "alighting",
      boarding: "Alighting",
      headsign: "Drop-off terminal",
      scheduled_departure_time: "2026-10-26T07:46:00Z",
      expected_departure_time: null,
      is_skipped: true,
    },
    {
      route: "77",
      visit_id: "alighting-live",
      boarding: "Alighting",
      scheduled_departure_time: "2026-10-26T07:51:00Z",
      expected_departure_time: "2026-10-26T07:54:00Z",
    },
  ];
  const defaultCard = await board(hass);
  expect(defaultCard.shadowRoot!.querySelectorAll("button")).toHaveLength(1);
  expect(defaultCard.shadowRoot!.querySelectorAll("select")).toHaveLength(0);
  expect(defaultCard.shadowRoot!.textContent).not.toContain(
    "Drop-off terminal",
  );

  const card = await board(hass, { show_arrivals: true });
  const root = card.shadowRoot!;
  const arrivals = root.querySelector<HTMLButtonElement>(
    'button[value="arrivals"]',
  )!;
  expect(arrivals.getAttribute("aria-pressed")).toBe("false");
  expect(root.textContent).not.toContain("Drop-off terminal");
  arrivals.click();
  await card.updateComplete;
  expect(arrivals.getAttribute("aria-pressed")).toBe("true");
  const [unknown, predicted] = root.querySelectorAll(".departure");
  expect(unknown!.textContent).toContain("Drop-off terminal");
  expect(unknown!.textContent).toContain("Scheduled stop time");
  expect(unknown!.textContent).toContain("Skipped");
  expect(unknown!.textContent).not.toContain("Expected stop time");
  expect(predicted!.textContent).toContain("Expected stop time");
  expect(
    [...predicted!.querySelectorAll("time")].map((el) => el.dateTime),
  ).toEqual(["2026-10-26T07:51:00Z", "2026-10-26T07:54:00Z"]);
  expect(root.textContent).not.toContain("Springfield Central");
  expect(root.textContent).not.toContain("Next service");
  expect(root.querySelector("select")).toBeNull();

  const refreshed = structuredClone(hass);
  refreshed.states[stopBoard]!.attributes.arrivals = [];
  card.hass = refreshed;
  await card.updateComplete;
  expect(arrivals.getAttribute("aria-pressed")).toBe("true");
  expect(root.querySelector('[role="status"]')!.textContent).toContain(
    "No arrivals found",
  );
});

it("filters before limiting, keeps selections on refresh, and separates board states", async () => {
  const hass = structuredClone(fixture) as HomeAssistant;
  hass.states[stopBoard]!.attributes.departures = [
    {
      route: "Zeta",
      headsign: "Park",
      direction: "Outbound",
      visit_id: "park",
      scheduled_departure_time: "2026-10-26T07:46:00Z",
    },
    ...[
      ["Inbound", "City"],
      ["Inbound", "River"],
      ["Outbound", "Beach"],
    ].map(([direction, headsign], index) => ({
      route: "T2",
      route_id: "T:Train:T2",
      direction,
      headsign,
      visit_id: headsign,
      scheduled_departure_time: `2026-10-26T07:5${index}:00Z`,
    })),
  ];
  const card = await board(hass, { show_filters: true, max_departures: 1 });
  const root = card.shadowRoot!;
  const field = (name: string) =>
    root.querySelector<HTMLSelectElement>(`select[name="${name}"]`)!;
  const choose = async (name: string, value: string) => {
    const select = field(name);
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await card.updateComplete;
  };
  const visibleVisit = () => root.querySelector(".departure")?.textContent;
  const status = () => root.querySelector('[role="status"]')?.textContent;
  expect(visibleVisit()).toContain("Park");
  await choose("order", "route");
  expect(visibleVisit()).toContain("City");
  await choose("route", "T:Train:T2");
  await choose("direction", "Inbound");
  expect(visibleVisit()).toContain("City");
  expect(root.textContent).toContain("Showing 1 of 2 departures");

  const refreshed = structuredClone(hass);
  refreshed.states[stopBoard]!.attributes.departures = [
    { route: "Zeta", direction: "Outbound", headsign: "Park" },
  ];
  card.hass = refreshed;
  await card.updateComplete;
  expect(field("route").value).toBe("T:Train:T2");
  expect(field("route").selectedOptions[0]?.text).toBe("T2");
  expect(field("direction").value).toBe("Inbound");
  expect(field("order").value).toBe("route");
  expect(visibleVisit()).toBeUndefined();
  expect(status()).toContain("No services match the selected filters");
  root.querySelector<HTMLButtonElement>(".clear-board-filters")!.click();
  await card.updateComplete;
  expect(field("route").value).toBe("");
  expect(field("direction").value).toBe("");
  expect(field("order").value).toBe("route");
  expect(visibleVisit()).toContain("Park");

  const empty = structuredClone(refreshed);
  empty.states[stopBoard]!.attributes.departures = [];
  card.hass = empty;
  await card.updateComplete;
  expect(status()).toContain("No services found");
  expect(root.querySelector(".clear-board-filters")).toBeNull();

  const unavailable = structuredClone(empty);
  unavailable.states[stopBoard]!.state = "unavailable";
  card.hass = unavailable;
  await card.updateComplete;
  expect(status()).toContain("Transport information is unavailable");
  expect(root.querySelector("select")).toBeNull();
});

it("limits alerts and distinguishes no disruptions from unavailable data", async () => {
  const hass = structuredClone(fixture) as HomeAssistant;
  const state = hass.states["sensor.renamed_journey_disruptions"]!;
  state.attributes.disruptions = [{ title: "First" }, { title: "Second" }];
  const card = document.createElement("translink-alerts-card") as AlertsCard;
  card.setConfig({
    type: "custom:translink-alerts-card",
    entity: state.entity_id,
    max_alerts: 1,
  });
  card.hass = hass;
  document.body.append(card);
  await card.updateComplete;
  expect(card.shadowRoot!.querySelectorAll(".alert")).toHaveLength(1);
  expect(card.shadowRoot!.textContent).toContain("Showing 1 of 2 alerts");
  expect(card.shadowRoot!.textContent).not.toContain("Second");
  const empty = structuredClone(hass);
  empty.states[state.entity_id]!.attributes.disruptions = [];
  card.hass = empty;
  await card.updateComplete;
  expect(card.shadowRoot!.textContent).toContain(
    "No active disruptions reported",
  );
});

it("keeps scheduled predictions, signed delays and missing-data relationships distinct", async () => {
  const hass = structuredClone(fixture) as HomeAssistant;
  const leg = (
    hass.states["sensor.renamed_journey_itinerary"]!.attributes.legs as Record<
      string,
      unknown
    >[]
  )[1]!;
  leg.callingStopsSource = "scheduled_with_realtime";
  leg.callingStops = [
    {
      name: "On schedule",
      scheduledTimeUtc: "2026-10-26T07:46:00Z",
      realtime: {
        departureTimeUtc: "2026-10-26T07:46:00Z",
        departureDelaySeconds: 0,
      },
    },
    {
      name: "Early",
      scheduledTimeUtc: "2026-10-26T07:50:00Z",
      realtime: {
        arrivalTimeUtc: "2026-10-26T07:48:00Z",
        arrivalDelaySeconds: -120,
      },
    },
    {
      name: "Late",
      scheduledTimeUtc: "2026-10-26T07:52:00Z",
      realtime: { departureDelaySeconds: 120 },
    },
    { name: "Skipped", realtime: { scheduleRelationship: "skipped" } },
    {
      stopId: "600010",
      realtime: { scheduleRelationship: "no_data", departureDelaySeconds: 120 },
    },
  ];
  const card = await journey(hass);
  card.shadowRoot!.querySelector<HTMLButtonElement>(".disclosure")!.click();
  await card.updateComplete;
  const calls = [...card.shadowRoot!.querySelectorAll(".call")];
  expect(calls).toHaveLength(5);
  expect(calls[0]!.textContent).toContain("No delay reported");
  expect(calls[0]!.querySelector("time")!.getAttribute("datetime")).toBe(
    "2026-10-26T07:46:00Z",
  );
  expect(calls[1]!.textContent).toContain("-2 min");
  expect(calls[1]!.textContent).toContain("Predicted");
  expect(calls[2]!.textContent).toContain("+2 min");
  expect(calls[3]!.textContent).toContain("Stop skipped");
  expect(calls[4]!.textContent).toContain("Stop 600010");
  expect(calls[4]!.textContent).toContain("No prediction available");
  expect(calls[4]!.textContent).not.toContain("+2 min");
});

it("shows the active vehicle while scheduled and first-service information stay the same", async () => {
  const hass = structuredClone(fixture) as HomeAssistant;
  const card = await journey(hass);
  const root = card.shadowRoot!;
  const firstService = root.querySelector(".chip")?.textContent;
  const times = root.querySelector(".timing")?.textContent;
  const activeVehicle = () => root.querySelector(".active-vehicle");

  expect(firstService).toContain("T2 Springfield Central");
  expect(times).toContain("5:46 pm");
  expect(activeVehicle()?.textContent).toContain("Ferny Grove");
  expect(activeVehicle()?.textContent).toContain("Train 103");
  expect(
    activeVehicle()?.querySelector('[role="status"]')?.textContent,
  ).toMatch(/Live position · 5:48 pm/);
  expect(root.textContent).not.toContain("153.2321");
  root.querySelector<HTMLButtonElement>(".disclosure")!.click();
  await card.updateComplete;
  expect(root.querySelector(".leg[aria-current=step]")?.textContent).toContain(
    "Active leg",
  );

  for (const [status, label] of [
    ["stale", "Position stale"],
    ["ambiguous", "Multiple matching vehicles"],
    ["no_position", "No live position"],
    ["no_active_leg", "No active vehicle"],
    ["disabled", "Tracking disabled"],
  ]) {
    const next = structuredClone(hass);
    next.states[vehicleTracker]!.state = "unknown";
    next.states[vehicleTracker]!.attributes = {
      ...next.states[vehicleTracker]!.attributes,
      position_status: status,
      active_leg_index: status === "no_active_leg" ? null : 0,
    };
    card.hass = next;
    await card.updateComplete;
    expect(
      activeVehicle()?.querySelector('[role="status"]')?.textContent?.trim(),
    ).toBe(label);
    expect(activeVehicle()?.textContent).not.toContain("Train 103");
    expect(root.querySelector(".chip")?.textContent).toBe(firstService);
    expect(root.querySelector(".timing")?.textContent).toBe(times);
  }

  const unavailable = structuredClone(hass);
  unavailable.states[vehicleTracker]!.state = "unavailable";
  card.hass = unavailable;
  await card.updateComplete;
  expect(activeVehicle()).toBeNull();
  expect(root.querySelector(".leg[aria-current]")).toBeNull();
  const absent = structuredClone(hass);
  delete absent.states[vehicleTracker];
  card.hass = absent;
  await card.updateComplete;
  expect(activeVehicle()).toBeNull();
  expect(root.querySelector(".chip")?.textContent).toBe(firstService);
  expect(root.querySelector(".timing")?.textContent).toBe(times);
});

it("shows stop timetable times and upstream visit statuses separately", async () => {
  const hass = structuredClone(fixture) as HomeAssistant;
  const entity = "sensor.renamed_stop_departures_board";
  hass.states[entity]!.attributes.departures = [
    {
      route: "T2",
      visit_id: "one",
      boarding: "Boarding",
      scheduled_departure_time: "2026-10-26T07:46:00Z",
      expected_departure_time: "2026-10-26T07:52:00Z",
      time_source: "realtime",
      is_cancelled: true,
      is_extra: true,
      is_skipped: false,
      platform_change: { old_platform: "1", platform: "<script>2</script>" },
    },
    {
      route: "T3",
      visit_id: "two",
      scheduled_departure_time: "2026-10-26T07:48:00Z",
      time_source: "scheduled",
      is_skipped: true,
      is_cancelled: "true",
    },
  ];
  const card = document.createElement(
    "translink-departures-card",
  ) as DeparturesCard;
  card.setConfig({ type: "custom:translink-departures-card", entity });
  card.hass = hass;
  document.body.append(card);
  await card.updateComplete;

  expect(card.shadowRoot!.textContent).toContain("Stop timetable");
  const [realtime, scheduled] = card.shadowRoot!.querySelectorAll(".departure");
  expect(realtime!.textContent).toContain("Scheduled");
  expect(realtime!.textContent).toContain("Expected");
  expect(
    [...realtime!.querySelectorAll("time")].map((time) =>
      time.getAttribute("datetime"),
    ),
  ).toEqual(["2026-10-26T07:46:00Z", "2026-10-26T07:52:00Z"]);
  expect(realtime!.textContent).toContain("Cancelled");
  expect(realtime!.textContent).toContain("Boarding only");
  expect(realtime!.textContent).toContain("Extra service");
  expect(realtime!.textContent).not.toContain("Skipped");
  expect(realtime!.textContent).toMatch(
    /Platform change: 1 →\s*<script>2<\/script>/,
  );
  expect(realtime!.querySelector("script")).toBeNull();
  expect(scheduled!.textContent).toContain("Scheduled");
  expect(scheduled!.textContent).toContain("Skipped");
  expect(scheduled!.textContent).not.toMatch(
    /Expected|Live|Cancelled|Boarding only/,
  );
});

it("calls the planner once with Brisbane inputs when Plan is submitted", async () => {
  const callService = vi.fn().mockResolvedValue({
    response: {
      ...alternatives,
      total_alternatives: 0,
      returned: 0,
      alternatives: [],
    },
  });
  const card = await journey({ ...fixture, callService });
  expect(card.shadowRoot!.querySelector(".planner")).toBeNull();
  card.setConfig({ ...card.config, show_planner: true });
  await card.updateComplete;
  const form =
    card.shadowRoot!.querySelector<HTMLFormElement>(".planner form")!;
  form.querySelector<HTMLInputElement>('[name="date"]')!.value = "2026-10-06";
  form.querySelector<HTMLInputElement>('[name="time"]')!.value = "00:00";
  form.querySelector<HTMLSelectElement>('[name="time_search_mode"]')!.value =
    "ArriveBefore";
  form.requestSubmit();
  await vi.waitFor(() => {
    expect(card.shadowRoot!.textContent).toContain("No journeys found");
  });
  expect(callService).toHaveBeenCalledExactlyOnceWith(
    "translink",
    "plan_journey",
    {
      entity_id: card.config.entity,
      date: "2026-10-06",
      time: "00:00",
      time_search_mode: "ArriveBefore",
      sort_by: "departure",
      limit: 10,
    },
    undefined,
    false,
    true,
  );
});

it("reorders results locally and shows missing values, counts and safe notice text", async () => {
  const callService = vi.fn().mockResolvedValue({ response: alternatives });
  const card = await journey({ ...fixture, callService });
  card.setConfig({ ...card.config, show_planner: true, alternatives_limit: 3 });
  await card.updateComplete;
  const root = card.shadowRoot!;
  root.querySelector<HTMLFormElement>(".planner form")!.requestSubmit();
  await vi.waitFor(() =>
    expect(root.querySelectorAll(".alternative")).toHaveLength(3),
  );
  const options = [...root.querySelectorAll(".alternative")];
  expect(options[0]?.textContent).toContain("56 min");
  expect(options[0]?.textContent).toContain("1 service notice");
  expect(options[0]?.textContent).toContain(
    '<img src="https://example.invalid/notice">',
  );
  expect(options[0]?.querySelector("img")).toBeNull();
  expect(options[1]?.textContent).toContain("Planner first");
  expect(
    [...options[2]!.querySelectorAll("dd")].map((cell) =>
      cell.textContent?.trim(),
    ),
  ).toEqual(["—", "—", "—", "—"]);

  const sort = root.querySelector<HTMLSelectElement>(".planner-sort select")!;
  sort.value = "duration";
  sort.dispatchEvent(new Event("change"));
  await card.updateComplete;

  expect(root.querySelector(".alternative")?.textContent).toContain("41 min");
  expect(callService).toHaveBeenCalledTimes(1);
  card.setConfig({ ...card.config, alternatives_limit: 1 });
  await card.updateComplete;
  expect(root.querySelectorAll(".alternative")).toHaveLength(1);
});

it("shows loading and action failure without a second in-flight request", async () => {
  let rejectPlan!: (reason: { message: string }) => void;
  const callService = vi.fn(
    () =>
      new Promise<{ response: JourneyAlternatives }>((_resolve, reject) => {
        rejectPlan = reject;
      }),
  );
  const card = await journey({ ...fixture, callService });
  card.setConfig({ ...card.config, show_planner: true });
  await card.updateComplete;
  const root = card.shadowRoot!;
  const form = root.querySelector<HTMLFormElement>(".planner form")!;
  form.requestSubmit();
  form.requestSubmit();
  await card.updateComplete;
  expect(root.querySelector(".planner [role=status]")?.textContent).toContain(
    "Planning journey",
  );
  expect(form.querySelector("button")?.disabled).toBe(true);
  expect(callService).toHaveBeenCalledTimes(1);
  rejectPlan({ message: "Planner unavailable" });
  await vi.waitFor(() =>
    expect(root.querySelector("[role=alert]")?.textContent).toBe(
      "Planner unavailable",
    ),
  );
  expect(form.querySelector("button")?.disabled).toBe(false);
});

it("opens the share preview explicitly and restores focus on Cancel and Escape", async () => {
  const hass = structuredClone(fixture) as HomeAssistant;
  const callService = vi.fn().mockResolvedValue(undefined);
  const card = await journey({ ...hass, callService });
  card.setConfig({ ...card.config, title: "Private card title" });
  await card.updateComplete;
  const root = card.shadowRoot!;
  const share = root.querySelector<HTMLButtonElement>(".share-toggle")!;
  expect(share).not.toBeNull();
  expect(root.querySelector(".share-preview")).toBeNull();
  share.click();
  await card.updateComplete;
  const heading = root.querySelector("#share-preview-heading");
  expect(root.activeElement).toBe(heading);
  const preview = root.querySelector(".share-preview")!;
  expect(preview.textContent).toContain("Kippa-Ring station");
  expect(preview.textContent).not.toMatch(
    /Private card title|14 Private Street/,
  );
  expect(callService).not.toHaveBeenCalled();
  root.querySelector<HTMLButtonElement>(".share-cancel")!.click();
  await card.updateComplete;
  expect(root.querySelector(".share-preview")).toBeNull();
  expect(root.activeElement).toBe(share);
  share.click();
  await card.updateComplete;
  root.activeElement!.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
  );
  await card.updateComplete;
  expect(root.querySelector(".share-preview")).toBeNull();
  expect(root.activeElement).toBe(share);
  expect(root.querySelector(".timing")).not.toBeNull();
});

async function openSharePreview(card: JourneyCard) {
  const root = card.shadowRoot!;
  root.querySelector<HTMLButtonElement>(".share-toggle")!.click();
  await card.updateComplete;
  return root;
}

it("targets only the configured writable calendar with the previewed fields", async () => {
  const callService = vi
    .fn()
    .mockRejectedValueOnce(new Error("ServiceNotSupported"))
    .mockResolvedValueOnce(undefined);
  const card = await journey({ ...structuredClone(fixture), callService });
  card.setConfig({
    ...card.config,
    calendar_entity: "calendar.travel",
    legs_expanded: true,
  });
  await card.updateComplete;
  const root = await openSharePreview(card);
  expect(callService).not.toHaveBeenCalled();
  const add = root.querySelector<HTMLButtonElement>(".share-add-calendar")!;
  add.click();
  add.click();
  await vi.waitFor(() =>
    expect(root.querySelector(".share-status")?.textContent).toContain(
      "Could not add",
    ),
  );
  expect(callService).toHaveBeenCalledExactlyOnceWith(
    "calendar",
    "create_event",
    {
      summary: "Kippa-Ring station → Fortitude Valley station · Scheduled",
      description: root.querySelector(".share-text")?.textContent,
      location: "Kippa-Ring station",
      start_date_time: "2026-10-26T07:46:00.000Z",
      end_date_time: "2026-10-26T08:39:00.000Z",
    },
    { entity_id: "calendar.travel" },
    false,
  );
  expect(root.querySelector(".timing")).not.toBeNull();
  expect(root.querySelectorAll(".leg")).toHaveLength(2);
  add.click();
  await vi.waitFor(() =>
    expect(root.querySelector(".share-status")?.textContent).toContain(
      "Added to calendar",
    ),
  );
  const hass = card.hass!;
  card.hass = {
    ...hass,
    states: {
      ...hass.states,
      "calendar.travel": {
        ...hass.states["calendar.travel"]!,
        attributes: { supported_features: 2 },
      },
    },
  };
  await card.updateComplete;
  expect(root.querySelector(".share-add-calendar")).toBeNull();
  card.setConfig({ ...card.config, calendar_entity: "calendar.unavailable" });
  await card.updateComplete;
  expect(root.querySelector(".share-preview")).toBeNull();
  await openSharePreview(card);
  expect(root.querySelector(".share-add-calendar")).toBeNull();
});

it("shares and copies only the visible text on click and handles capability failures", async () => {
  const share = vi
    .fn()
    .mockResolvedValueOnce(undefined)
    .mockRejectedValueOnce(new DOMException("Cancelled", "AbortError"))
    .mockRejectedValueOnce(new Error("Permission denied"));
  const writeText = vi
    .fn()
    .mockResolvedValueOnce(undefined)
    .mockRejectedValueOnce(new Error("Clipboard blocked"));
  vi.stubGlobal("navigator", { share, clipboard: { writeText } });
  const root = await openSharePreview(await journey(fixture));
  const preview = root.querySelector(".share-text")?.textContent;
  const shareButton = root.querySelector<HTMLButtonElement>(".share-native")!;
  const copyButton = root.querySelector<HTMLButtonElement>(".share-copy")!;
  const status = root.querySelector(".share-status")!;
  expect(share).not.toHaveBeenCalled();
  expect(writeText).not.toHaveBeenCalled();
  shareButton.click();
  expect(share).toHaveBeenCalledExactlyOnceWith({ text: preview });
  shareButton.click();
  await vi.waitFor(() => expect(share).toHaveBeenCalledTimes(2));
  expect(status.textContent?.trim()).toBe("");
  shareButton.click();
  await vi.waitFor(() =>
    expect(status.textContent).toContain("Could not share"),
  );
  copyButton.click();
  expect(writeText).toHaveBeenCalledExactlyOnceWith(preview);
  await vi.waitFor(() => expect(status.textContent).toContain("Copied"));
  copyButton.click();
  await vi.waitFor(() =>
    expect(status.textContent).toContain("Could not copy"),
  );
  expect(root.querySelector(".timing")).not.toBeNull();
});

it("downloads a local ICS file without Web Share, clipboard or secure crypto", async () => {
  vi.stubGlobal("navigator", {});
  vi.stubGlobal("crypto", {});
  const createObjectURL = vi.fn().mockReturnValue("blob:local-calendar");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal(
    "URL",
    class extends URL {
      static override createObjectURL = createObjectURL;
      static override revokeObjectURL = revokeObjectURL;
    },
  );
  const download = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe("translink-journey.ics");
      expect(this.href).toBe("blob:local-calendar");
    });
  const root = await openSharePreview(await journey(fixture));
  expect(root.querySelector(".share-native")).toBeNull();
  expect(root.querySelector(".share-copy")).toBeNull();
  expect(root.querySelector(".share-text")?.textContent).toContain("RPSP");
  expect(createObjectURL).not.toHaveBeenCalled();
  root.querySelector<HTMLButtonElement>(".share-download")!.click();
  expect(createObjectURL).toHaveBeenCalledExactlyOnceWith(expect.any(Blob));
  expect(download).toHaveBeenCalledTimes(1);
  await vi.waitFor(() =>
    expect(revokeObjectURL).toHaveBeenCalledExactlyOnceWith(
      "blob:local-calendar",
    ),
  );
});

it("keeps only validated public trip timetable links in the leg details", async () => {
  const card = await journey(fixture);
  card.setConfig({ ...card.config, legs_expanded: true });
  await card.updateComplete;
  const root = card.shadowRoot!;
  const link = root.querySelector<HTMLAnchorElement>(".trip-timetable")!;
  expect(link.href).toBe(
    "https://jp.translink.com.au/plan-your-journey/timetables/trip/s_T_RPSP_8_20261026_39766414",
  );
  expect(link.getAttribute("aria-label")).toBe("Trip timetable · RPSP");
  expect(link.target).toBe("_blank");
  expect(link.rel).toBe("noopener noreferrer");

  const hass: HomeAssistant = structuredClone(fixture);
  const legs = hass.states[card.config.entity!]!.attributes.legs as Record<
    string,
    unknown
  >[];
  legs[1]!.timetableUrl = "https://example.invalid/?token=secret";
  card.hass = hass;
  await card.updateComplete;
  expect(root.querySelector(".trip-timetable")).toBeNull();
  expect(root.querySelectorAll(".leg")).toHaveLength(2);
  expect(
    (await openSharePreview(card)).querySelector(".share-text")?.textContent,
  ).not.toContain("example.invalid");
});

it("updates the preview on journey changes and closes it when no services remain", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  const card = await journey(fixture);
  const root = await openSharePreview(card);
  const hass: HomeAssistant = structuredClone(fixture);
  hass.states["sensor.renamed_journey_next_departure"]!.state =
    "2026-10-26T07:55:00Z";
  card.hass = hass;
  await card.updateComplete;
  expect(root.querySelector(".share-status")?.textContent).toContain(
    "Journey updated",
  );
  expect(root.querySelector(".share-text")?.textContent).toContain("5:55 pm");
  root.querySelector<HTMLButtonElement>(".share-copy")!.click();
  expect(writeText).toHaveBeenCalledExactlyOnceWith(
    root.querySelector(".share-text")?.textContent,
  );
  card.hass = emptyJourney();
  await card.updateComplete;
  expect(root.querySelector(".share-preview")).toBeNull();
  expect(root.querySelector(".share-toggle")).toBeNull();
  expect(root.textContent).toContain("No services found");
  card.hass = fixture;
  await card.updateComplete;
  expect(root.querySelector(".share-toggle")).not.toBeNull();
  expect(root.querySelector(".share-preview")).toBeNull();
});

it("keeps sharing and the ordinary journey display when calendar export is unavailable", async () => {
  const hass: HomeAssistant = structuredClone(fixture);
  hass.states["sensor.renamed_journey_next_departure"]!.state = "unknown";
  const legs = hass.states["sensor.renamed_journey_itinerary"]!.attributes
    .legs as Record<string, unknown>[];
  legs[0]!.departureTimeUtc = "2026-10-26T07:39:00";
  const card = await journey(hass);
  card.setConfig({
    ...card.config,
    calendar_entity: "calendar.travel",
    legs_expanded: true,
  });
  await card.updateComplete;
  const root = await openSharePreview(card);
  expect(
    root.querySelector<HTMLButtonElement>(".share-download")?.disabled,
  ).toBe(true);
  expect(root.querySelector("#calendar-unavailable")?.textContent).toContain(
    "requires valid scheduled",
  );
  expect(root.querySelector(".share-add-calendar")).toBeNull();
  expect(root.querySelector(".share-text")?.textContent).toContain("RPSP");
  expect(root.querySelectorAll(".leg")).toHaveLength(2);

  card.setConfig({ ...card.config, show_actions: false });
  await card.updateComplete;
  expect(root.querySelector(".share-toggle")).toBeNull();
  expect(root.querySelector(".share-preview")).toBeNull();
  expect(root.querySelector(".trip-timetable")).toBeNull();
  expect(root.querySelector(".timing")).not.toBeNull();
  expect(root.querySelectorAll(".leg")).toHaveLength(2);
});

it.each([
  { show_actions: "false" },
  { calendar_entity: "sensor.calendar" },
  { calendar_entity: 1 },
  { calendar_entity: "calendar.travel\n" },
])("rejects invalid share settings %j synchronously", (options) => {
  const card = document.createElement("translink-journey-card") as JourneyCard;
  expect(() =>
    card.setConfig({
      type: "custom:translink-journey-card",
      ...options,
    } as CardConfig),
  ).toThrow(/show_actions|calendar_entity/);
});
