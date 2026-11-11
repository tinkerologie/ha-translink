import {
  available,
  rows,
  stopName,
  text,
  time,
  timeZoneLabel,
} from "./helpers";
import { strings } from "./strings";
import type { EntityState, HomeAssistant, JourneyLegAttributes } from "./types";

const labels = strings.share;
const timetableOrigin = "https://jp.translink.com.au";
const timetablePath =
  /^\/plan-your-journey\/timetables\/trip\/[A-Za-z0-9_-]{1,128}$/;

export function validateTimetableUrl(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  try {
    const url = new URL(value);
    if (
      url.protocol === "https:" &&
      url.origin === timetableOrigin &&
      !url.username &&
      !url.password &&
      !url.search &&
      !url.hash &&
      timetablePath.test(url.pathname) &&
      value === timetableOrigin + url.pathname
    )
      return url.href;
  } catch {
    return undefined;
  }
  return undefined;
}

// Date.parse also accepts local times and can roll an impossible day into the
// following month. Require a real calendar date and an explicit UTC offset.
function scheduledTime(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const match =
    /^(\d{4})-(\d{2})-(\d{2})T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(
      value,
    );
  if (!match || match[0] !== value) return undefined;
  const [, yyyy, mm, dd] = match;
  const year = Number(yyyy);
  const month = Number(mm);
  const day = Number(dd);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (!year || day < 1 || day > (days[month - 1] ?? 0)) return undefined;
  const instant = new Date(value);
  if (!Number.isFinite(instant.getTime())) return undefined;
  const utcYear = instant.getUTCFullYear();
  return utcYear >= 1 && utcYear <= 9999 ? instant.toISOString() : undefined;
}

type PublicStop = { name: string; platform?: string };

type ShareLeg =
  | { walk: true }
  | {
      walk: false;
      mode: string;
      route?: string;
      routeCode?: string;
      origin?: PublicStop;
      destination?: PublicStop;
      departure?: string;
      arrival?: string;
      timetable?: string;
    };

function publicStop(
  proven: boolean | undefined,
  value: unknown,
  platform: unknown,
): PublicStop | undefined {
  const name = proven === true ? stopName(value) : undefined;
  return name ? { name, platform: text(platform) } : undefined;
}

function shareLeg(leg: JourneyLegAttributes): ShareLeg {
  const mode = text(leg.travelMode) ?? labels.transit;
  if (mode.toLowerCase() === "walk") return { walk: true };
  const routeCode = text(leg.routeCode);
  return {
    walk: false,
    mode,
    route: routeCode ?? text(leg.route),
    routeCode,
    origin: publicStop(leg.originIsPublicStop, leg.origin, leg.originPlatform),
    destination: publicStop(
      leg.destinationIsPublicStop,
      leg.destination,
      leg.destinationPlatform,
    ),
    departure: scheduledTime(leg.departureTimeUtc),
    arrival: scheduledTime(leg.arrivalTimeUtc),
    timetable: validateTimetableUrl(leg.timetableUrl),
  };
}

function stopLabel(stop: PublicStop): string {
  return stop.platform
    ? `${stop.name} · ${labels.platform} ${stop.platform}`
    : stop.name;
}

function legLines(leg: ShareLeg, hass?: HomeAssistant): string[] {
  if (leg.walk) return [labels.walk];
  return [
    [leg.mode, leg.route].filter(Boolean).join(" "),
    leg.origin && `${labels.boarding} · ${stopLabel(leg.origin)}`,
    leg.departure && `${labels.departure} · ${time(leg.departure, hass, true)}`,
    leg.destination && `${labels.alighting} · ${stopLabel(leg.destination)}`,
    leg.arrival && `${labels.arrival} · ${time(leg.arrival, hass, true)}`,
    leg.timetable && `${labels.timetable} · ${leg.timetable}`,
  ].filter((line): line is string => typeof line === "string");
}

interface CalendarEvent extends Record<string, unknown> {
  summary: string;
  description: string;
  location?: string;
  start_date_time: string;
  end_date_time: string;
}

type CalendarExport =
  | { available: false; reason: string }
  | {
      available: true;
      data: CalendarEvent;
      displayStart: string;
      displayEnd: string;
      uid: string;
    };

export type JourneySharePayload =
  | { available: false; reason: string }
  | {
      available: true;
      shareText: string;
      timeZone: string;
      calendar: CalendarExport;
    };

function calendarUid(start: string, end: string, routes: string[]): string {
  // FNV-1a over the same UTF-8 data for every export, including on HTTP.
  let hash = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(
    JSON.stringify([start, end, routes]),
  )) {
    hash = Math.imul(hash ^ byte, 0x01000193);
  }
  return `${(hash >>> 0).toString(16).padStart(8, "0")}@ha-translink`;
}

export function buildJourneySharePayload(
  state: EntityState | undefined,
  related: Record<string, EntityState>,
  hass?: HomeAssistant,
): JourneySharePayload {
  if (!available(state) || !text(state.state))
    return { available: false, reason: labels.unavailable };
  const legs: JourneyLegAttributes[] = rows(state.attributes.legs);
  if (
    related.status?.state === "no_service" ||
    state.state === "no_service" ||
    !legs.length
  )
    return { available: false, reason: strings.noServices };

  const shareLegs = legs.map(shareLeg);
  const transit = shareLegs.filter((leg) => !leg.walk);
  const boarding = transit.find((leg) => leg.origin)?.origin?.name;
  const alighting = transit.findLast((leg) => leg.destination)?.destination
    ?.name;
  const title =
    [boarding, alighting].filter(Boolean).join(" → ") || labels.journey;
  const start =
    scheduledTime(related.next_departure?.state) ??
    scheduledTime(legs[0]?.departureTimeUtc);
  const end =
    scheduledTime(related.arrival_time?.state) ??
    scheduledTime(legs.at(-1)?.arrivalTimeUtc);
  const displayStart = time(start, hass, true);
  const displayEnd = time(end, hass, true);
  const timeZone = timeZoneLabel(hass);
  const shareText = [
    title,
    `${labels.timeZone} · ${timeZone}`,
    start && `${labels.departure} · ${displayStart}`,
    end && `${labels.arrival} · ${displayEnd}`,
    "",
    ...shareLegs.map((leg) => legLines(leg, hass).join("\n")),
    "",
    labels.scheduleNotice,
    labels.checkRealtime,
  ]
    .filter((line) => line !== undefined)
    .join("\n");

  let calendar: CalendarExport;
  if (!start || !end) {
    calendar = { available: false, reason: labels.missingTimes };
  } else if (Date.parse(end) <= Date.parse(start)) {
    calendar = { available: false, reason: labels.invalidOrder };
  } else {
    const location = transit[0]?.origin?.name;
    calendar = {
      available: true,
      data: {
        summary: `${title} · ${strings.scheduled}`,
        description: shareText,
        ...(location ? { location } : {}),
        start_date_time: start,
        end_date_time: end,
      },
      displayStart,
      displayEnd,
      uid: calendarUid(
        start,
        end,
        transit.map((leg) => leg.routeCode ?? ""),
      ),
    };
  }
  return { available: true, shareText, timeZone, calendar };
}

function escapeCalendarText(value: string): string {
  return value
    .replaceAll("\\", "\\\\")
    .replaceAll(",", "\\,")
    .replaceAll(";", "\\;")
    .replace(/\r\n|\r|\n/g, "\\n");
}

function utcCalendarTime(value: string): string {
  return value.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

function foldCalendarLine(line: string): string {
  const encoder = new TextEncoder();
  let folded = "";
  let octets = 0;
  for (const character of line) {
    const size = encoder.encode(character).length;
    if (octets + size > 75) {
      folded += "\r\n ";
      octets = 1;
    }
    folded += character;
    octets += size;
  }
  return folded;
}

export function buildCalendarFile(
  calendar: Extract<CalendarExport, { available: true }>,
  now = new Date(),
): string {
  const { data, uid } = calendar;
  return [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Home Assistant Translink//Journey//EN",
    "BEGIN:VEVENT",
    `UID:${uid}`,
    `DTSTAMP:${utcCalendarTime(now.toISOString())}`,
    `DTSTART:${utcCalendarTime(data.start_date_time)}`,
    `DTEND:${utcCalendarTime(data.end_date_time)}`,
    `SUMMARY:${escapeCalendarText(data.summary)}`,
    `DESCRIPTION:${escapeCalendarText(data.description)}`,
    ...(data.location ? [`LOCATION:${escapeCalendarText(data.location)}`] : []),
    "END:VEVENT",
    "END:VCALENDAR",
    "",
  ]
    .map(foldCalendarLine)
    .join("\r\n");
}
