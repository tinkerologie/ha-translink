import { afterEach, expect, it } from "vitest";
import "../src/index";
import fixture from "./fixtures/hass.json";
import type { TranslinkCard } from "../src/cards";
import type { HomeAssistant } from "../src/types";

const entity = "sensor.renamed_journey_progress";
afterEach(() => document.body.replaceChildren());

async function progress(state: string, attributes: Record<string, unknown>) {
  const hass = structuredClone(fixture) as HomeAssistant;
  hass.states[entity] = {
    entity_id: entity,
    state,
    attributes: { journey_id: "fixture", ...attributes },
  };
  hass.entities![entity] = {
    entity_id: entity,
    translation_key: "journey_progress",
    platform: "translink",
    device_id: "journey",
  };
  const card = document.createElement(
    "translink-progress-card",
  ) as TranslinkCard;
  card.setConfig({ type: "custom:translink-progress-card", entity });
  card.hass = hass;
  document.body.append(card);
  await card.updateComplete;
  return card.shadowRoot!;
}

it.each([
  ["schedule", "Scheduled"],
  ["realtime_schedule", "Live prediction"],
  ["vehicle", "Vehicle observation"],
  ["unknown", "Unknown"],
])("shows active-leg provenance from %s", async (source, label) => {
  const root = await progress("in_progress", {
    active_leg_index: source === "unknown" ? null : 0,
    active_leg_source: source,
    progress_legs: [
      { index: 0, mode: "Train", route: "CAIP", color: "#08368d" },
    ],
  });
  expect(root.textContent).toContain(label);
  if (source !== "unknown")
    expect(root.querySelector('[aria-current="step"]')?.textContent).toContain(
      "CAIP",
    );
});

it("shows a skipped stop and keeps stale vehicle evidence out of the card", async () => {
  const root = await progress("in_progress", {
    active_leg_source: "schedule",
    vehicle_observation: { fresh: false, stop_name: "Darra" },
    next_action: {
      type: "alight",
      stop_name: "Springfield",
      skipped: true,
      time_source: "scheduled",
      scheduled_time: "2026-10-26T08:15:00Z",
    },
  });
  expect(root.textContent).toContain("Springfield");
  expect(root.textContent).toContain("Skipped");
  expect(root.textContent).not.toContain("Darra");
  expect(root.textContent).not.toContain("Live");
});

it("keeps unavailable, unknown and cancelled states distinct", async () => {
  expect((await progress("unavailable", {})).textContent).toContain(
    "unavailable",
  );
  expect((await progress("unknown", {})).textContent).toContain(
    "Journey progress is unknown",
  );
  expect((await progress("cancelled", {})).textContent).toContain(
    "Journey cancelled",
  );
});
