import {
  LitElement,
  html,
  nothing,
  type PropertyValues,
  type TemplateResult,
} from "lit";
import {
  available,
  brisbaneInputDefaults,
  modeIcon,
  normalizeDepartures,
  number,
  routeColors,
  rows,
  siblings,
  sortJourneyAlternatives,
  statusLabel,
  stopName,
  stub,
  text,
  time,
  validTime,
} from "./helpers";
import { strings } from "./strings";
import { cardStyles } from "./styles";
import type {
  CardConfig,
  EntityState,
  HomeAssistant,
  JourneyAlternative,
  JourneyAlternatives,
  JourneySort,
  RegistryEntry,
  Row,
} from "./types";

const MAX_ALTERNATIVES_LIMIT = 10;
const DEFAULT_ALTERNATIVES_LIMIT = 5;

const labels: Record<string, string> = {
  entity: "Translink entity",
  title: "Title",
  show_fare: "Show fare",
  legs_expanded: "Expand journey details",
  show_disruptions: "Show service alerts",
  max_departures: "Maximum departures",
  show_platform: "Show platform",
  max_alerts: "Maximum alerts",
  show_planner: "Show journey planner",
  alternatives_limit: "Maximum alternatives",
};
function form(role: string, fields: string[]) {
  return {
    schema: [
      {
        name: "entity",
        required: true,
        selector: {
          entity: { filter: { domain: "sensor", integration: "translink" } },
        },
      },
      { name: "title", selector: { text: {} } },
      ...fields.map((name) => ({
        name,
        selector:
          name === "alternatives_limit"
            ? { number: { min: 1, max: MAX_ALTERNATIVES_LIMIT, mode: "box" } }
            : name.startsWith("max_")
              ? { number: { min: 1, max: 20, mode: "box" } }
              : { boolean: {} },
      })),
    ],
    computeLabel: (schema: { name: string }) =>
      labels[schema.name] ?? schema.name,
    computeHelper: (schema: { name: string }) =>
      schema.name === "entity"
        ? `Choose the ${role.replaceAll("_", " ")} sensor.`
        : undefined,
  };
}
function chip(label: unknown, vehicle: unknown, color?: unknown) {
  const colors = routeColors(color);
  return html`<span
    class="chip"
    style=${`background:${colors.background};color:${colors.foreground}`}
    ><ha-icon .icon=${modeIcon(vehicle)} aria-hidden="true"></ha-icon
    ><span>${text(label) ?? text(vehicle) ?? "Transit"}</span></span
  >`;
}
function value(state: EntityState | undefined): string | undefined {
  return available(state) ? state.state : undefined;
}

export abstract class TranslinkCard extends LitElement {
  static override properties = {
    hass: { attribute: false },
    config: { state: true },
    expanded: { state: true },
  };
  static override styles = cardStyles;
  static role = "";
  static title = "";
  declare hass?: HomeAssistant;
  declare config: CardConfig;
  declare expanded: boolean;
  protected abstract entityRole: string;
  protected abstract defaultTitle: string;
  protected abstract icon: string;
  constructor() {
    super();
    this.config = { type: "" };
    this.expanded = false;
  }
  static getStubConfig(hass?: HomeAssistant) {
    return stub(hass, this.role);
  }
  static getEntitySuggestion(hass: HomeAssistant, entity: string) {
    const entry = hass.entities?.[entity];
    return (
      entry?.platform === "translink" && entry.translation_key === this.role
    );
  }
  setConfig(config: CardConfig): void {
    if (!config || typeof config.type !== "string")
      throw new Error("Invalid Translink card configuration");
    if (config.entity !== undefined && typeof config.entity !== "string")
      throw new Error("Entity must be a string");
    if (config.title !== undefined && typeof config.title !== "string")
      throw new Error("Title must be a string");
    for (const key of [
      "show_fare",
      "legs_expanded",
      "show_disruptions",
      "show_platform",
    ] as const) {
      if (config[key] !== undefined && typeof config[key] !== "boolean")
        throw new Error(`${key} must be a boolean`);
    }
    for (const key of ["max_departures", "max_alerts"] as const) {
      const v = config[key];
      if (v !== undefined && (!Number.isInteger(v) || v < 1 || v > 20))
        throw new Error(`${key} must be between 1 and 20`);
    }
    this.config = { ...config };
    this.expanded = config.legs_expanded ?? false;
  }
  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }
  getCardSize() {
    return 5;
  }
  protected override shouldUpdate(changed: PropertyValues<this>): boolean {
    if (!changed.has("hass") || changed.size > 1) return true;
    const old = changed.get("hass") as HomeAssistant | undefined;
    if (
      !old ||
      old.entities !== this.hass?.entities ||
      old.devices !== this.hass?.devices ||
      old.locale !== this.hass?.locale ||
      old.config !== this.hass?.config ||
      old.language !== this.hass?.language
    )
      return true;
    const current = siblings(this.hass, this.config.entity);
    const previous = siblings(old, this.config.entity);
    return (
      old.states[this.config.entity ?? ""] !==
        this.hass?.states[this.config.entity ?? ""] ||
      Object.keys(current).length !== Object.keys(previous).length ||
      Object.keys(current).some((key) => current[key] !== previous[key])
    );
  }
  protected get related() {
    return siblings(this.hass, this.config.entity);
  }
  protected openMoreInfo(): void {
    if (this.config.entity)
      this.dispatchEvent(
        new CustomEvent("hass-more-info", {
          detail: { entityId: this.config.entity },
          bubbles: true,
          composed: true,
        }),
      );
  }
  protected abstract renderContent(state: EntityState): TemplateResult;
  protected override render() {
    const state = this.hass?.states[this.config.entity ?? ""];
    const entry = this.hass?.entities?.[this.config.entity ?? ""];
    const device = entry?.device_id
      ? this.hass?.devices?.[entry.device_id]
      : undefined;
    let message: string | undefined;
    if (!this.config.entity) message = strings.choose;
    else if (!this.hass?.states) message = strings.loading;
    else if (!state) message = strings.missing;
    else if (!available(state)) message = strings.unavailable;
    else if (!this.hass.entities) message = strings.loading;
    else if (
      entry?.platform !== "translink" ||
      entry.translation_key !== this.entityRole
    )
      message = strings.unsuitable;
    return html`<ha-card>
      <header>
        <span class="icon"
          ><ha-icon .icon=${this.icon} aria-hidden="true"></ha-icon
        ></span>
        <div class="headings">
          <h2>${this.config.title ?? this.defaultTitle}</h2>
          ${device
            ? html`<div class="subtitle">
                ${device.name_by_user ?? device.name}
              </div>`
            : nothing}
        </div>
        ${state
          ? html`<button
              class="icon-button"
              aria-label=${strings.moreInfo}
              @click=${this.openMoreInfo}
            >
              <ha-icon
                icon="mdi:information-outline"
                aria-hidden="true"
              ></ha-icon>
            </button>`
          : nothing}
      </header>
      <div class="content">
        ${message
          ? html`<div class="state" role="status">
              <ha-icon
                icon="mdi:information-outline"
                aria-hidden="true"
              ></ha-icon
              ><span>${message}</span>
            </div>`
          : state
            ? this.renderContent(state)
            : nothing}
        ${this.renderExtra(entry)}
      </div>
    </ha-card>`;
  }
  protected renderExtra(
    _entry?: RegistryEntry,
  ): TemplateResult | typeof nothing {
    return nothing;
  }
  protected formatTime(value: unknown, date = false) {
    return time(value, this.hass, date);
  }
}

type PlannerState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "complete"; result: JourneyAlternatives };

export class JourneyCard extends TranslinkCard {
  static override properties = {
    ...TranslinkCard.properties,
    planner: { state: true },
    plannerSort: { state: true },
  };
  static override role = "itinerary";
  static override title = strings.journey;
  static getConfigForm() {
    return form(this.role, [
      "show_fare",
      "legs_expanded",
      "show_disruptions",
      "show_planner",
      "alternatives_limit",
    ]);
  }
  protected entityRole = "itinerary";
  protected defaultTitle = strings.journey;
  protected icon = "mdi:routes";
  private planner?: PlannerState;
  private plannerSort: JourneySort = "departure";
  private readonly plannerDefaults = brisbaneInputDefaults();

  override setConfig(config: CardConfig): void {
    if (
      config?.show_planner !== undefined &&
      typeof config.show_planner !== "boolean"
    )
      throw new Error("show_planner must be a boolean");
    const limit = config?.alternatives_limit;
    if (
      limit !== undefined &&
      (!Number.isInteger(limit) || limit < 1 || limit > MAX_ALTERNATIVES_LIMIT)
    )
      throw new Error("alternatives_limit must be between 1 and 10");
    const oldEntity = this.config.entity;
    super.setConfig(config);
    if (oldEntity !== config.entity || !config.show_planner)
      this.planner = undefined;
  }

  protected override renderExtra(entry?: RegistryEntry) {
    if (
      !this.config.show_planner ||
      entry?.platform !== "translink" ||
      entry.translation_key !== this.entityRole
    )
      return nothing;
    const result =
      this.planner?.status === "complete" ? this.planner.result : undefined;
    const sorted = result
      ? sortJourneyAlternatives(result.alternatives, this.plannerSort).slice(
          0,
          this.config.alternatives_limit ?? DEFAULT_ALTERNATIVES_LIMIT,
        )
      : [];
    const planNoticeTitles = result?.plan_notices
      ?.map(({ title }) => title)
      .filter(Boolean);

    return html`<section class="planner" aria-label="Journey planner">
      <h3>Plan a journey</h3>
      <form @submit=${this.submitPlan}>
        <label>
          Date (Brisbane)
          <input
            name="date"
            type="date"
            required
            .value=${this.plannerDefaults.date}
          />
        </label>
        <label>
          Time (Brisbane)
          <input
            name="time"
            type="time"
            required
            .value=${this.plannerDefaults.time}
          />
        </label>
        <label>
          Time preference
          <select name="time_search_mode">
            <option value="LeaveAfter">Leave after</option>
            <option value="ArriveBefore">Arrive before</option>
          </select>
        </label>
        <button type="submit" ?disabled=${this.planner?.status === "loading"}>
          Plan
        </button>
      </form>
      <label class="planner-sort">
        Sort by
        <select
          .value=${this.plannerSort}
          @change=${(event: Event) => {
            this.plannerSort = (event.target as HTMLSelectElement)
              .value as JourneySort;
          }}
        >
          <option value="departure">Departure</option>
          <option value="arrival">Arrival</option>
          <option value="duration">Duration</option>
        </select>
      </label>
      ${this.planner?.status === "loading"
        ? html`<div role="status">Planning journey…</div>`
        : nothing}
      ${this.planner?.status === "error"
        ? html`<div role="alert">${this.planner.message}</div>`
        : nothing}
      ${result && !sorted.length
        ? html`<div role="status">No journeys found</div>`
        : nothing}
      ${sorted.length
        ? html`<ol class="alternatives" aria-label="Journey alternatives">
            ${sorted.map((alternative) => this.renderAlternative(alternative))}
          </ol>`
        : nothing}
      ${result?.truncated
        ? html`<div class="secondary">
            Received ${result.returned} of ${result.total_alternatives}
            journeys.
          </div>`
        : nothing}
      ${planNoticeTitles?.length
        ? html`<div class="secondary">
            Planner notices · ${planNoticeTitles.join("; ")}
          </div>`
        : nothing}
    </section>`;
  }

  private async submitPlan(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const { hass } = this;
    if (this.planner?.status === "loading") return;
    if (!hass?.callService) {
      this.planner = {
        status: "error",
        message: "Journey planning is unavailable",
      };
      return;
    }
    const fields = new FormData(event.currentTarget as HTMLFormElement);
    const pending = { status: "loading" } as const;
    this.planner = pending;
    try {
      const { response } = await hass.callService(
        "translink",
        "plan_journey",
        {
          entity_id: this.config.entity,
          date: fields.get("date"),
          time: fields.get("time"),
          time_search_mode: fields.get("time_search_mode"),
          sort_by: this.plannerSort,
          limit: MAX_ALTERNATIVES_LIMIT,
        },
        undefined,
        false,
        true,
      );
      if (this.planner === pending)
        this.planner = { status: "complete", result: response };
    } catch (error) {
      if (this.planner !== pending) return;
      const message = text((error as { message?: unknown } | null)?.message);
      this.planner = {
        status: "error",
        message: message ?? "Unable to plan journey",
      };
    }
  }

  private renderAlternative(option: JourneyAlternative) {
    const notices = option.notices.length;
    return html`<li class="alternative">
      <dl>
        <div>
          <dt>Departure</dt>
          <dd>${this.formatTime(option.departure, true)}</dd>
        </div>
        <div>
          <dt>Arrival</dt>
          <dd>${this.formatTime(option.arrival, true)}</dd>
        </div>
        <div>
          <dt>Duration</dt>
          <dd>
            ${option.duration_mins === null
              ? "—"
              : `${option.duration_mins} min`}
          </dd>
        </div>
        <div>
          <dt>Transfers</dt>
          <dd>${option.transfers ?? "—"}</dd>
        </div>
      </dl>
      ${option.planner_first
        ? html`<span class="secondary">Planner first</span>`
        : nothing}
      ${notices
        ? html`<details>
            <summary>
              ${notices} service notice${notices === 1 ? "" : "s"}
            </summary>
            <ul>
              ${option.notices.map(
                ({ title }) => html`<li>${title ?? "Service notice"}</li>`,
              )}
            </ul>
          </details>`
        : nothing}
    </li>`;
  }
  protected renderContent(state: EntityState) {
    const related = this.related;
    const legs = rows(state.attributes.legs);
    if (value(related.status) === "no_service" || !legs.length)
      return html`
        <div class="state" role="status">${strings.noServices}</div>
        ${this.renderDisruptionStrip(related.disruptions)}
      `;
    const first = legs[0]!;
    const last = legs[legs.length - 1]!;
    const service = related.next_service?.attributes ?? {};
    const duration = number(value(related.duration));
    const transfers = number(value(related.transfers));
    const walking = number(value(related.walking_distance));
    const fare = number(value(related.fare));
    return html`
      <div class="timing">
        <div>
          <div class="secondary">Departure · Scheduled</div>
          <div class="time">
            ${this.formatTime(
              value(related.next_departure) ?? first.departureTimeUtc,
            )}
          </div>
          <div class="stop-name">${stopName(first.origin) ?? "Origin"}</div>
          ${text(first.originPlatform)
            ? html`<div class="secondary">
                Platform ${first.originPlatform}
              </div>`
            : nothing}
        </div>
        <ha-icon icon="mdi:arrow-right" aria-hidden="true"></ha-icon>
        <div class="destination">
          <div class="secondary">Arrival · Scheduled</div>
          <div class="time">
            ${this.formatTime(
              value(related.arrival_time) ?? last.arrivalTimeUtc,
            )}
          </div>
          <div class="stop-name">
            ${stopName(last.destination) ?? "Destination"}
          </div>
          ${text(last.destinationPlatform)
            ? html`<div class="secondary">
                Platform ${last.destinationPlatform}
              </div>`
            : nothing}
        </div>
      </div>
      ${chip(
        service.route_name ?? first.route,
        service.vehicle ?? first.travelMode,
        service.route_color ?? first.routeColor,
      )}
      <div class="status">
        <ha-icon icon="mdi:clock-outline" aria-hidden="true"></ha-icon
        >${statusLabel(value(related.status), number(value(related.delay)))}
      </div>
      <div class="metrics">
        ${duration !== undefined
          ? html`<span class="metric"
              ><ha-icon icon="mdi:timer-outline" aria-hidden="true"></ha-icon
              >${duration} min</span
            >`
          : nothing}
        ${transfers !== undefined
          ? html`<span class="metric"
              >${transfers === 0
                ? "Direct service"
                : `${transfers} transfer${transfers === 1 ? "" : "s"}`}</span
            >`
          : nothing}
        ${walking !== undefined && walking > 0
          ? html`<span class="metric"
              ><ha-icon icon="mdi:walk" aria-hidden="true"></ha-icon>${walking}
              m</span
            >`
          : nothing}
        ${this.config.show_fare !== false && fare !== undefined
          ? html`<span class="metric"
              >${new Intl.NumberFormat(this.hass?.locale?.language ?? "en-AU", {
                style: "currency",
                currency: "AUD",
              }).format(fare)}</span
            >`
          : nothing}
      </div>
      ${this.renderDisruptionStrip(related.disruptions)}
      <button
        class="disclosure"
        aria-expanded=${this.expanded}
        aria-controls="journey-legs"
        @click=${() => {
          this.expanded = !this.expanded;
        }}
      >
        <span
          >Journey details · ${legs.length}
          leg${legs.length === 1 ? "" : "s"}</span
        ><ha-icon
          .icon=${this.expanded ? "mdi:chevron-up" : "mdi:chevron-down"}
          aria-hidden="true"
        ></ha-icon>
      </button>
      ${this.expanded
        ? html`<ol class="legs" id="journey-legs">
            ${legs.map((leg) => this.renderLeg(leg))}
          </ol>`
        : html`<div id="journey-legs" hidden></div>`}
    `;
  }
  private renderDisruptionStrip(state?: EntityState) {
    const alerts = number(value(state));
    return this.config.show_disruptions !== false &&
      alerts !== undefined &&
      alerts > 0
      ? html`<div class="alert-strip">
          <ha-icon icon="mdi:alert-outline" aria-hidden="true"></ha-icon
          ><span
            >${alerts} service alert${alerts === 1 ? "" : "s"} ·
            ${text(state?.attributes.latest_title) ??
            "Check service information"}</span
          >
        </div>`
      : nothing;
  }
  private renderLeg(leg: Row) {
    const calls = rows(leg.callingStops);
    const source = text(leg.callingStopsSource);
    const showCalls =
      calls.length > 0 &&
      ["scheduled", "scheduled_with_realtime", "realtime_partial"].includes(
        source ?? "",
      );
    return html`<li class="leg">
      ${chip(leg.route ?? leg.travelMode, leg.travelMode, leg.routeColor)}
      <div class="endpoint">
        <div>
          <div class="label">${stopName(leg.origin) ?? "Origin"}</div>
          ${text(leg.originPlatform)
            ? html`<div class="secondary">Platform ${leg.originPlatform}</div>`
            : nothing}
        </div>
        <time datetime=${text(leg.departureTimeUtc) ?? ""}
          >${this.formatTime(leg.departureTimeUtc)}</time
        >
      </div>
      <div class="endpoint">
        <div>
          <div class="label">${stopName(leg.destination) ?? "Destination"}</div>
          ${text(leg.destinationPlatform)
            ? html`<div class="secondary">
                Platform ${leg.destinationPlatform}
              </div>`
            : nothing}
        </div>
        <time datetime=${text(leg.arrivalTimeUtc) ?? ""}
          >${this.formatTime(leg.arrivalTimeUtc)}</time
        >
      </div>
      <div class="secondary">
        ${number(leg.durationMins) ?? "—"}
        min${number(leg.numberOfStops) ? ` · ${leg.numberOfStops} stops` : ""} ·
        Scheduled
      </div>
      ${showCalls
        ? html`<details class="stop-details">
            <summary>Calling stops · ${calls.length}</summary>
            <div class="note">
              ${source === "realtime_partial"
                ? "Partial real-time list · scheduled times unavailable"
                : "Scheduled calling times"}
            </div>
            <ol class="calling-stops">
              ${calls.map((call) =>
                this.renderCallingStop(call, source === "realtime_partial"),
              )}
            </ol>
          </details>`
        : nothing}
    </li>`;
  }
  private renderCallingStop(call: Row, partial: boolean) {
    const realtime = rows([call.realtime])[0];
    const predicted =
      validTime(realtime?.departureTimeUtc) ??
      validTime(realtime?.arrivalTimeUtc);
    const scheduled = validTime(call.scheduledTimeUtc);
    const delay =
      number(realtime?.departureDelaySeconds) ??
      number(realtime?.arrivalDelaySeconds);
    const relationship = text(realtime?.scheduleRelationship);
    const actualTime = partial ? predicted : scheduled;
    return html`<li class="call">
      <div>
        <div>
          ${stopName(call.name) ?? `Stop ${text(call.stopId) ?? "unknown"}`}
        </div>
        ${text(call.platform)
          ? html`<div class="secondary">Platform ${call.platform}</div>`
          : nothing}
        ${relationship === "skipped"
          ? html`<div class="secondary">Stop skipped</div>`
          : relationship === "no_data"
            ? html`<div class="secondary">No prediction available</div>`
            : nothing}
      </div>
      <div>
        <time datetime=${actualTime ?? ""}>${this.formatTime(actualTime)}</time>
        ${partial
          ? html`<span class="prediction">Predicted</span>`
          : predicted
            ? html`<span class="prediction"
                >Predicted ${this.formatTime(predicted)}</span
              >`
            : nothing}
        ${delay !== undefined && relationship !== "no_data"
          ? html`<span class="prediction"
              >${delay === 0
                ? "No delay reported"
                : `${delay > 0 ? "+" : ""}${Math.round(delay / 60)} min`}</span
            >`
          : nothing}
      </div>
    </li>`;
  }
}

export class DeparturesCard extends TranslinkCard {
  static override role = "departures_board";
  static override title = strings.departures;
  static getConfigForm() {
    return form(this.role, ["max_departures", "show_platform"]);
  }
  protected entityRole = "departures_board";
  protected defaultTitle = strings.departures;
  protected icon = "mdi:train-bus";
  protected renderContent(state: EntityState) {
    const departures = normalizeDepartures(state.attributes.departures);
    if (!departures.length)
      return html`<div class="state" role="status">${strings.noServices}</div>`;
    const delay = number(value(this.related.delay));
    return html`<div class="secondary">
        Upcoming departures · Planner results
      </div>
      ${delay !== undefined && delay > 0
        ? html`<div class="alert-strip">
            Next service: reported delay +${delay} min
          </div>`
        : nothing}
      <ol class="departures">
        ${departures.slice(0, this.config.max_departures ?? 5).map(
          (row) =>
            html`<li class="departure">
              <div>
                ${chip(row.route, row.vehicle, row.color)}${row.headsign
                  ? html`<div class="destination-name">${row.headsign}</div>`
                  : nothing}${this.config.show_platform !== false &&
                row.platform
                  ? html`<div class="secondary">Platform ${row.platform}</div>`
                  : nothing}
              </div>
              <div class="when">
                <time datetime=${row.time ?? ""}
                  >${this.formatTime(row.time)}</time
                >
                <div class="secondary">Scheduled</div>
              </div>
            </li>`,
        )}
      </ol>
      ${departures.length > (this.config.max_departures ?? 5)
        ? html`<div class="note">
            Showing ${this.config.max_departures ?? 5} of ${departures.length}
            departures
          </div>`
        : nothing}`;
  }
}

export class AlertsCard extends TranslinkCard {
  static override role = "disruptions";
  static override title = strings.alerts;
  static getConfigForm() {
    return form(this.role, ["max_alerts"]);
  }
  protected entityRole = "disruptions";
  protected defaultTitle = strings.alerts;
  protected icon = "mdi:alert-circle-outline";
  protected renderContent(state: EntityState) {
    const alerts = rows(state.attributes.disruptions);
    if (!alerts.length)
      return html`<div class="state" role="status">
        <ha-icon icon="mdi:check-circle-outline" aria-hidden="true"></ha-icon
        >${strings.noAlerts}
      </div>`;
    return html`<div class="secondary">
        ${alerts.length} service alert${alerts.length === 1 ? "" : "s"} reported
      </div>
      <ul class="alerts">
        ${alerts.slice(0, this.config.max_alerts ?? 5).map(
          (alert, index) =>
            html`<li class="alert">
              <div class="alert-title">
                <ha-icon icon="mdi:alert-outline" aria-hidden="true"></ha-icon>
                <div>
                  <h3>${text(alert.title) ?? "Service disruption"}</h3>
                  <div class="secondary">
                    ${[text(alert.severity), text(alert.route), text(alert.leg)]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                </div>
              </div>
              ${validTime(alert.starts_utc) || validTime(alert.ends_utc)
                ? html`<div class="note">
                    ${validTime(alert.starts_utc)
                      ? `From ${this.formatTime(alert.starts_utc, true)}`
                      : ""}${validTime(alert.ends_utc)
                      ? ` Until ${this.formatTime(alert.ends_utc, true)}`
                      : ""}
                  </div>`
                : nothing}
              ${text(alert.cause) || text(alert.effect)
                ? html`<div class="note">
                    ${[text(alert.cause), text(alert.effect)]
                      .filter(Boolean)
                      .map((v) => v!.replaceAll("_", " "))
                      .join(" · ")}
                  </div>`
                : nothing}
              ${text(alert.description)
                ? html`<details>
                    <summary aria-label=${`Details for alert ${index + 1}`}>
                      Show alert details
                    </summary>
                    <div class="description">${alert.description}</div>
                  </details>`
                : nothing}
            </li>`,
        )}
      </ul>
      ${alerts.length > (this.config.max_alerts ?? 5)
        ? html`<div class="note">
            Showing ${this.config.max_alerts ?? 5} of ${alerts.length} alerts
          </div>`
        : nothing}`;
  }
}
