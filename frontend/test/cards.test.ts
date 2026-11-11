import { afterEach, describe, expect, it } from "vitest";
import "../src/index";
import { AlertsCard, DeparturesCard, JourneyCard } from "../src/cards";
import fixture from "./fixtures/hass.json";
import type { CardConfig, HomeAssistant } from "../src/types";
afterEach(() => document.body.replaceChildren());
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
const journeyDisruptions = "sensor.renamed_journey_disruptions";
function emptyJourney(
  status = "no_service",
  disruptionCount = "1",
  disruptionTitle: string | null = "Line closure",
): HomeAssistant {
  const hass = structuredClone(fixture) as HomeAssistant;
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
  it("registers exactly three cards with native editor schemas", () => {
    expect(window.customCards).toHaveLength(3);
    expect(JourneyCard.getConfigForm().schema[0]?.selector).toMatchObject({
      entity: { filter: { integration: "translink" } },
    });
    expect(JourneyCard.getStubConfig(fixture)).toEqual({
      entity: "sensor.renamed_journey_itinerary",
    });
  });
  it("renders scheduled journeys and toggles details, without fabricated tracking", async () => {
    const card = await journey(fixture);
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
  )[0]!;
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
  )[0]!;
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

it("shows stop timetable times and upstream visit statuses separately", async () => {
  const hass = structuredClone(fixture) as HomeAssistant;
  const entity = "sensor.renamed_stop_departures_board";
  hass.states[entity]!.attributes.departures = [
    {
      route: "T2",
      visit_id: "one",
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
  expect(realtime!.textContent).toContain("Extra service");
  expect(realtime!.textContent).not.toContain("Skipped");
  expect(realtime!.textContent).toMatch(
    /Platform change: 1 →\s*<script>2<\/script>/,
  );
  expect(realtime!.querySelector("script")).toBeNull();
  expect(scheduled!.textContent).toContain("Scheduled");
  expect(scheduled!.textContent).toContain("Skipped");
  expect(scheduled!.textContent).not.toMatch(/Expected|Live|Cancelled/);
});
