import { html, nothing } from "lit";
import { chip, form, TranslinkCard } from "./cards";
import { number, rows, stopName, text, validTime } from "./helpers";
import { strings } from "./strings";
import type {
  EntityState,
  ProgressActionAttributes,
  ProgressAttributes,
  ProgressLegAttributes,
} from "./types";

const sources = {
  vehicle: "Vehicle observation",
  realtime_schedule: "Live prediction",
  schedule: strings.scheduled,
  unknown: "Unknown",
};

const states: Record<string, string> = {
  no_service: strings.noServices,
  not_started: "Journey not started",
  in_progress: "Journey in progress",
  finished: "Journey finished",
  cancelled: "Journey cancelled",
  unknown: "Journey progress is unknown",
};

const actions = {
  board: "Board at",
  transfer: "Transfer at",
  alight: "Alight at",
};

const stopStatuses: Record<string, string> = {
  STOPPED_AT: "Vehicle stopped at",
  INCOMING_AT: "Vehicle approaching",
  IN_TRANSIT_TO: "Vehicle heading to",
};

export class ProgressCard extends TranslinkCard {
  static override role = "journey_progress";
  static override title = "Journey progress";
  static getConfigForm() {
    return form(this.role, []);
  }
  protected entityRole = ProgressCard.role;
  protected defaultTitle = ProgressCard.title;
  protected icon = "mdi:map-marker-path";

  protected override stateIsAvailable(state: EntityState) {
    return (
      super.stateIsAvailable(state) ||
      (state.state === "unknown" && !!text(state.attributes.journey_id))
    );
  }

  protected renderContent(state: EntityState) {
    const attrs = state.attributes as ProgressAttributes;
    const legs = rows(attrs.progress_legs) as ProgressLegAttributes[];
    const active = number(attrs.active_leg_index);
    const source =
      sources[attrs.active_leg_source ?? "unknown"] ?? sources.unknown;
    const observation = attrs.vehicle_observation;
    const currentStop =
      stopName(observation?.stop_name) ?? text(observation?.stop_id);
    const stopStatus = stopStatuses[observation?.status ?? ""];
    return html`
      <div role="status">${states[state.state] ?? states.unknown}</div>
      ${legs.length
        ? html`
            <div class="secondary">${strings.activeLeg} · ${source}</div>
            <ol class="progress-legs" aria-label="Journey legs">
              ${legs.map((leg) => this.renderLeg(leg, active))}
            </ol>
          `
        : nothing}
      ${attrs.next_action ? this.renderAction(attrs.next_action) : nothing}
      ${observation?.fresh === true && currentStop && stopStatus
        ? html`<p class="secondary">${stopStatus} ${currentStop}</p>`
        : nothing}
    `;
  }

  private renderLeg(leg: ProgressLegAttributes, active: number | undefined) {
    const current = active !== undefined && number(leg.index) === active;
    const origin = stopName(leg.origin?.name);
    const destination = stopName(leg.destination?.name);
    return html`<li
      class="progress-leg"
      aria-current=${current ? "step" : nothing}
    >
      ${chip(leg.route, leg.mode, leg.color)}
      ${origin || destination
        ? html`<div>${[origin, destination].filter(Boolean).join(" → ")}</div>`
        : nothing}
    </li>`;
  }

  private renderAction(action: ProgressActionAttributes) {
    const predicted =
      action.time_source === "realtime"
        ? validTime(action.predicted_time)
        : undefined;
    const scheduled = validTime(action.scheduled_time);
    const timestamp = predicted ?? scheduled;
    const source = predicted
      ? sources.realtime_schedule
      : scheduled
        ? sources.schedule
        : sources.unknown;
    const stop =
      stopName(action.stop_name) ?? text(action.stop_id) ?? "unknown stop";
    const route = text(action.next_leg_route);
    const platform = text(action.next_leg_platform);
    return html`<div class="progress-action">
      <strong>${actions[action.type] ?? "Next stop"} ${stop}</strong>
      <div class="secondary">
        ${source}
        ${timestamp
          ? html` ·
              <time datetime=${timestamp}>${this.formatTime(timestamp)}</time>`
          : nothing}
        ${action.skipped === true ? html` · ${strings.skipped}` : nothing}
      </div>
      ${route || platform
        ? html`<div>
            ${[route, platform ? `Platform ${platform}` : undefined]
              .filter(Boolean)
              .join(" · ")}
          </div>`
        : nothing}
    </div>`;
  }
}
