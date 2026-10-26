import type {
  CardConfig,
  Departure,
  EntityState,
  HomeAssistant,
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
export function time(
  value: unknown,
  hass?: HomeAssistant,
  date = false,
): string {
  const iso = validTime(value);
  if (!iso) return "—";
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
    ).format(new Date(iso));
  } catch {
    return new Intl.DateTimeFormat("en-AU", {
      ...options,
      timeZone: "Australia/Brisbane",
    }).format(new Date(iso));
  }
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
export function normalizeDepartures(value: unknown): Departure[] {
  const seen = new Set<string>();
  return rows(value)
    .map((row) => ({
      tripId: text(row.trip_id ?? row.tripId),
      time: validTime(row.departure_time ?? row.departureTimeUtc),
      route: text(row.route) ?? text(row.routeCode) ?? "Transit",
      vehicle: text(row.vehicle) ?? text(row.travelMode) ?? "Transit",
      headsign: text(row.headsign) ?? text(row.destination),
      platform: text(row.platform) ?? text(row.originPlatform),
      color: text(row.routeColor),
    }))
    .filter((row) => {
      // Planner alternatives can share the exact same first departure.
      const key = JSON.stringify(row);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort(
      (a, b) =>
        (a.time ? Date.parse(a.time) : Infinity) -
        (b.time ? Date.parse(b.time) : Infinity),
    );
}
export function statusLabel(
  status: string | undefined,
  delay?: number,
): string {
  if (delay !== undefined && delay > 0) return `Reported delay +${delay} min`;
  const labels: Record<string, string> = {
    scheduled: "Scheduled",
    on_time: "No delay reported",
    delayed: "Delay reported",
    departed: "Departed (scheduled)",
    arrived: "Arrived (scheduled)",
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
