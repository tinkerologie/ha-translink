import { afterEach, describe, expect, it } from "vitest";
import "../src/index";
import { AlertsCard, JourneyCard } from "../src/cards";
import fixture from "./fixtures/hass.json";
import type { HomeAssistant } from "../src/types";
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
    const empty = structuredClone(fixture);
    empty.states["sensor.renamed_journey_status"].state = "no_service";
    expect((await journey(empty)).shadowRoot!.textContent).toContain(
      "No services found",
    );
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
