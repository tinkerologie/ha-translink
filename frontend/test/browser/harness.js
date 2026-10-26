// The harness supplies only an HA surface stub; live validation uses the real component.
customElements.define(
  "ha-card",
  class extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" }).innerHTML =
        `<style>:host{display:block;background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:12px}</style><slot></slot>`;
    }
  },
);
import "/custom_components/translink/frontend/translink-cards.js";
const hass = await (await fetch("/frontend/test/fixtures/hass.json")).json();
for (const [type, entity] of [
  ["journey", "sensor.renamed_journey_itinerary"],
  ["departures", "sensor.renamed_stop_departures_board"],
  ["alerts", "sensor.renamed_journey_disruptions"],
]) {
  const card = document.createElement(`translink-${type}-card`);
  card.setConfig({ type: `custom:translink-${type}-card`, entity });
  card.hass = hass;
  document.querySelector("main").append(card);
}
