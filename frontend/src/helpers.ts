import type {
  BoardFilterOption,
  BoardOrder,
  CardConfig,
  Departure,
  EntityState,
  HomeAssistant,
  JourneyAlternative,
  JourneySort,
  NoticePeriod,
  NoticeSelector,
  Row,
} from "./types";

export const text = (value: unknown): string | undefined =>
  typeof value === "string" && value.trim() && value !== "$undefined"
    ? value
    : undefined;
export const number = (value: unknown): number | undefined =>
  (typeof value === "number" || (typeof value === "string" && value.trim())) &&
  Number.isFinite(Number(value))
    ? Number(value)
    : undefined;
export const rows = (value: unknown): Row[] =>
  Array.isArray(value)
    ? value.filter(
        (item): item is Row =>
          !!item && typeof item === "object" && !Array.isArray(item),
      )
    : [];
export const validTime = (value: unknown): string | undefined => {
  const result = text(value);
  return result && Number.isFinite(Date.parse(result)) ? result : undefined;
};
export function normalizeNoticePeriods(value: unknown): NoticePeriod[] {
  return rows(value).flatMap((row) => {
    const start = validTime(row.start);
    const end = validTime(row.end);
    if ((row.start != null && !start) || (row.end != null && !end)) return [];
    if (!start && !end) return [];
    if (start && end && Date.parse(start) >= Date.parse(end)) return [];
    return [{ start, end }];
  });
}
export function normalizeNoticeSelectors(value: unknown): NoticeSelector[] {
  return rows(value).flatMap<NoticeSelector>((row) => {
    const selector = {
      agency_id: text(row.agency_id),
      route_id: text(row.route_id),
      trip_route_id: text(row.trip_route_id),
      route_type:
        typeof row.route_type === "number" && Number.isInteger(row.route_type)
          ? row.route_type
          : undefined,
      mode: text(row.mode),
      stop_id: text(row.stop_id),
      trip_id: text(row.trip_id),
    };
    const scope = row.scope;
    switch (scope) {
      case "network":
        return selector.agency_id ? [{ ...selector, scope }] : [];
      case "route":
        return selector.route_id || selector.trip_route_id
          ? [{ ...selector, scope }]
          : [];
      case "mode":
        return selector.route_type !== undefined
          ? [{ ...selector, scope }]
          : [];
      case "stop":
        return selector.stop_id ? [{ ...selector, scope }] : [];
      case "trip":
        return selector.trip_id ? [{ ...selector, scope }] : [];
      case "unknown":
        return [{ scope }];
      default:
        return [];
    }
  });
}
function clockFormatter(hass?: HomeAssistant, date = false) {
  const preference = hass?.locale?.time_format;
  const language = hass?.locale?.language ?? hass?.language ?? "en-AU";
  const hour12 =
    preference === "12" ? true : preference === "24" ? false : undefined;
  const zone =
    hass?.locale?.time_zone === "local"
      ? undefined
      : (hass?.config?.time_zone ?? "Australia/Brisbane");
  const options: Intl.DateTimeFormatOptions = {
    hour: "numeric",
    minute: "2-digit",
    hour12,
    timeZone: zone,
    ...(date ? ({ month: "short", day: "numeric" } as const) : {}),
  };
  try {
    return new Intl.DateTimeFormat(
      preference === "system" ? undefined : language,
      options,
    );
  } catch {
    return new Intl.DateTimeFormat("en-AU", {
      ...options,
      timeZone: "Australia/Brisbane",
    });
  }
}
export function time(
  value: unknown,
  hass?: HomeAssistant,
  date = false,
): string {
  const iso = validTime(value);
  return iso ? clockFormatter(hass, date).format(new Date(iso)) : "—";
}
export function timeZoneLabel(hass?: HomeAssistant): string {
  return clockFormatter(hass).resolvedOptions().timeZone;
}
export function siblings(
  hass: HomeAssistant | undefined,
  anchor?: string,
): Record<string, EntityState> {
  const registry = anchor ? hass?.entities?.[anchor] : undefined;
  if (!registry?.device_id || registry.platform !== "translink") return {};
  const result: Record<string, EntityState> = {};
  for (const entry of Object.values(hass?.entities ?? {})) {
    const state = hass?.states[entry.entity_id];
    if (
      entry.platform === "translink" &&
      entry.device_id === registry.device_id &&
      entry.translation_key &&
      state
    ) {
      result[entry.translation_key] = state;
    }
  }
  return result;
}
export function stub(
  hass: HomeAssistant | undefined,
  role: string,
): Partial<CardConfig> {
  const entry = Object.values(hass?.entities ?? {}).find(
    (item) =>
      item.platform === "translink" &&
      item.translation_key === role &&
      hass?.states[item.entity_id],
  );
  return entry ? { entity: entry.entity_id } : {};
}
function optionalBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}
export function normalizeDepartures(value: unknown): Departure[] {
  const seen = new Set<string>();
  return rows(value).flatMap((row) => {
    const departure = {
      tripId: text(row.trip_id ?? row.tripId),
      time: validTime(
        row.scheduled_departure_time ??
          row.departure_time ??
          row.departureTimeUtc,
      ),
      route: text(row.route) ?? text(row.routeCode) ?? "Transit",
      vehicle: text(row.vehicle) ?? text(row.travelMode) ?? "Transit",
      headsign: text(row.headsign) ?? text(row.destination),
      platform: text(row.platform) ?? text(row.originPlatform),
      color: text(row.route_color ?? row.routeColor),
    };
    const visitId = text(row.visit_id);
    // Preserve the seven-field key used by legacy planner departures.
    const key = visitId ? `visit:${visitId}` : JSON.stringify(departure);
    if (seen.has(key)) return [];
    seen.add(key);
    const change = rows([row.platform_change])[0];
    const source = row.time_source;
    return [
      {
        ...departure,
        visitId,
        expectedTime: validTime(row.expected_departure_time),
        timeSource:
          source === "scheduled" || source === "realtime" ? source : undefined,
        cancelled: optionalBoolean(row.is_cancelled),
        skipped: optionalBoolean(row.is_skipped),
        extra: optionalBoolean(row.is_extra),
        platformChange: change && {
          platform: text(change.platform),
          oldPlatform: text(change.old_platform),
          isSource: optionalBoolean(change.is_source),
        },
        boarding: text(row.boarding),
        routeId: text(row.route_id),
        direction: text(row.direction),
      } satisfies Departure,
    ];
  });
}
const boardLabels = new Intl.Collator(undefined, { numeric: true });

export function boardFilterOptions(
  visits: Departure[],
  field: "route" | "direction",
  selected?: BoardFilterOption,
): BoardFilterOption[] {
  const labelsByValue = new Map<string, Set<string>>();
  for (const visit of visits) {
    const label = visit[field];
    if (!label) continue;
    const value = field === "route" ? (visit.routeId ?? label) : label;
    const labels = labelsByValue.get(value) ?? new Set<string>();
    labels.add(label);
    labelsByValue.set(value, labels);
  }
  const options = [...labelsByValue].map(([value, labels]) => ({
    value,
    label: [...labels].sort(boardLabels.compare).join(" / "),
  }));
  if (selected && !labelsByValue.has(selected.value)) options.push(selected);
  return options.sort((a, b) => boardLabels.compare(a.label, b.label));
}

export function filterDepartures(
  visits: Departure[],
  route?: string,
  direction?: string,
): Departure[] {
  return visits.filter(
    (visit) =>
      (!route || (visit.routeId ?? visit.route) === route) &&
      (!direction || visit.direction === direction),
  );
}

export function orderDepartures(
  visits: Departure[],
  order: BoardOrder = "scheduled",
): Departure[] {
  return [...visits].sort((a, b) => {
    if (Boolean(a.time) !== Boolean(b.time)) return a.time ? -1 : 1;
    if (order === "route") {
      const byRoute = boardLabels.compare(a.route, b.route);
      if (byRoute !== 0) return byRoute;
    }
    return a.time && b.time ? Date.parse(a.time) - Date.parse(b.time) : 0;
  });
}

export function statusLabel(
  status: string | undefined,
  delay?: number,
): string {
  if (status === "cancelled") return "Cancelled";
  if (status === "boarding_skipped") return "Boarding stop skipped";
  if (delay !== undefined && delay > 0) return `Reported delay +${delay} min`;
  if (delay !== undefined && delay < 0) return `Reported early −${-delay} min`;
  const labels: Record<string, string> = {
    scheduled: "Scheduled · No real-time data used",
    on_time: "No delay reported",
    early: "Early",
    delayed: "Delay reported",
    departed: "Departed",
    arrived: "Arrived",
    no_service: "No services found",
  };
  return labels[status ?? ""] ?? "Schedule information";
}
export function routeColors(value: unknown): {
  background: string;
  foreground: string;
} {
  const color = text(value);
  if (!color || !/^#[\da-f]{6}$/i.test(color))
    return {
      background: "var(--secondary-background-color)",
      foreground: "var(--primary-text-color)",
    };
  const channels = [1, 3, 5].map((start) => {
    const c = parseInt(color.slice(start, start + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  const luminance =
    channels[0]! * 0.2126 + channels[1]! * 0.7152 + channels[2]! * 0.0722;
  return {
    background: color,
    foreground: luminance > 0.179 ? "#000000" : "#ffffff",
  };
}
export function modeIcon(value: unknown): string {
  const mode = String(value ?? "").toLowerCase();
  if (mode.includes("walk")) return "mdi:walk";
  if (mode.includes("train")) return "mdi:train";
  if (mode.includes("tram")) return "mdi:tram";
  if (mode.includes("ferry") || mode.includes("boat")) return "mdi:ferry";
  return "mdi:bus";
}
export const available = (state?: EntityState): state is EntityState =>
  !!state && !["unavailable", "unknown"].includes(state.state);

/** Compact a supplied station label; platform remains a separate labelled field. */
export function stopName(value: unknown): string | undefined {
  return text(value)?.replace(/, platform [^,]+(?:,.*)?$/i, "");
}

const plannerSortKeys = {
  departure: ["departure", "arrival", "duration_mins"],
  arrival: ["arrival", "departure", "duration_mins"],
  duration: ["duration_mins", "departure", "arrival"],
} as const;

export function sortJourneyAlternatives(
  alternatives: JourneyAlternative[],
  sortBy: JourneySort,
): JourneyAlternative[] {
  return [...alternatives].sort((left, right) => {
    for (const key of plannerSortKeys[sortBy]) {
      const a = left[key];
      const b = right[key];
      if (a === b) continue;
      if (a === null) return 1;
      if (b === null) return -1;
      return a < b ? -1 : 1;
    }
    return left.planner_index - right.planner_index;
  });
}

const brisbaneClock = new Intl.DateTimeFormat("en-AU", {
  timeZone: "Australia/Brisbane",
  hourCycle: "h23",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

export function brisbaneInputDefaults(now = new Date()) {
  const parts = Object.fromEntries(
    brisbaneClock.formatToParts(now).map(({ type, value }) => [type, value]),
  );
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    time: `${parts.hour}:${parts.minute}`,
  };
}
