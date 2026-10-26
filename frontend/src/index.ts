import { AlertsCard, DeparturesCard, JourneyCard } from "./cards";
import type { HomeAssistant } from "./types";
interface CustomCard {
  type: string;
  name: string;
  description: string;
  preview: boolean;
  documentationURL: string;
  getEntitySuggestion?: (
    hass: HomeAssistant,
    entity: string,
  ) => { config: { type: string; entity: string } } | null;
}
declare global {
  interface Window {
    customCards?: CustomCard[];
  }
}
for (const [tag, constructor, name, description] of [
  [
    "translink-journey-card",
    JourneyCard,
    "Translink Journey",
    "Journey times, route, platforms and expandable itinerary.",
  ],
  [
    "translink-departures-card",
    DeparturesCard,
    "Translink Departures",
    "Upcoming departures from your station or stop.",
  ],
  [
    "translink-alerts-card",
    AlertsCard,
    "Translink Service Alerts",
    "Disruptions affecting your journey or stop.",
  ],
] as const) {
  if (!customElements.get(tag)) customElements.define(tag, constructor);
  window.customCards ??= [];
  if (!window.customCards.some((card) => card.type === tag))
    window.customCards.push({
      type: tag,
      name,
      description,
      preview: true,
      documentationURL:
        "https://github.com/tinkerologie/ha-translink#dashboard-cards",
      getEntitySuggestion: (hass, entity) => {
        const entry = hass.entities?.[entity];
        return entry?.platform === "translink" &&
          entry.translation_key === constructor.role
          ? { config: { type: `custom:${tag}`, entity } }
          : null;
      },
    });
}
