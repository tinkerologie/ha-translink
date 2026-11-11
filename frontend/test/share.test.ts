import { expect, it } from "vitest";
import { siblings } from "../src/helpers";
import {
  buildJourneySharePayload,
  buildCalendarFile,
  validateTimetableUrl,
} from "../src/share";
import type { HomeAssistant, Row } from "../src/types";
import fixture from "./fixtures/hass.json";

const itinerary = "sensor.renamed_journey_itinerary";

function journeyData() {
  const hass: HomeAssistant = structuredClone(fixture);
  const state = hass.states[itinerary]!;
  const [, transit] = state.attributes.legs as Row[];
  const walk = {
    travelMode: "Walk",
    origin: "14 Private Street",
    originIsPublicStop: true,
    destination: "Private walking endpoint",
    departureTimeUtc: "2026-10-26T07:39:00Z",
    arrivalTimeUtc: "2026-10-26T07:46:00Z",
    coordinates: [-27.117, 153.177],
    polyline: "private-polyline",
  };
  state.attributes.legs = [
    walk,
    {
      ...transit,
      originIsPublicStop: true,
      destination: "17 Private Lane",
      destinationPlatform: "private-platform",
      destinationIsPublicStop: false,
      fare: "private-fare",
      tripId: "private-trip-id",
      token: "private-token",
      timetableUrl:
        "https://jp.translink.com.au/plan-your-journey/timetables/trip/s_T_RPSP_8_20261026_39766414",
    },
  ];
  return { hass, state, related: siblings(hass, itinerary) };
}

it("builds share text from public stops, scheduled fields, and walking mode alone", () => {
  const { hass, state, related } = journeyData();
  const result = buildJourneySharePayload(state, related, hass);
  expect(result.available).toBe(true);
  if (!result.available) throw new Error(result.reason);
  expect(result.shareText).toContain("Kippa-Ring station");
  expect(result.shareText).toContain("Platform 1");
  expect(result.shareText).toMatch(/\nWalk\n/);
  expect(result.shareText).toContain("Scheduled");
  expect(result.shareText).toContain("Australia/Brisbane");
  expect(result.shareText).toContain("Check realtime before travel");
  expect(JSON.stringify(result)).not.toMatch(
    /private|153\.177|27\.117|Predicted/i,
  );
});

it("exports the same scheduled UTC instants in Brisbane and UTC displays", () => {
  const { hass, state, related } = journeyData();
  related.next_departure = {
    ...related.next_departure!,
    state: "2026-10-26T17:46:00+10:00",
  };
  hass.locale = { ...hass.locale, time_format: "24" };
  const brisbane = buildJourneySharePayload(state, related, hass);
  const utc = buildJourneySharePayload(state, related, {
    ...hass,
    config: { time_zone: "UTC" },
  });
  if (
    !brisbane.available ||
    !brisbane.calendar.available ||
    !utc.available ||
    !utc.calendar.available
  )
    throw new Error("Calendar unavailable");
  expect(brisbane.shareText).toMatch(/Australia\/Brisbane/);
  expect(brisbane.shareText).toMatch(/17:46/);
  expect(utc.shareText).toMatch(/UTC/);
  expect(utc.shareText).toMatch(/\b0?7:46/);
  const now = new Date("2026-10-01T00:00:00Z");
  for (const payload of [brisbane, utc]) {
    if (!payload.calendar.available) throw new Error("Calendar unavailable");
    expect(payload.calendar.data).toEqual({
      summary: "Kippa-Ring station · Scheduled",
      description: payload.shareText,
      location: "Kippa-Ring station",
      start_date_time: "2026-10-26T07:46:00.000Z",
      end_date_time: "2026-10-26T08:39:00.000Z",
    });
    expect(payload.shareText).toContain("s_T_RPSP_8_20261026_39766414");
    const calendar = buildCalendarFile(payload.calendar, now);
    expect(calendar).toContain("DTSTAMP:20261001T000000Z\r\n");
    expect(calendar).toContain("DTSTART:20261026T074600Z\r\n");
    expect(calendar).toContain("DTEND:20261026T083900Z\r\n");
    expect(calendar).toContain("LOCATION:Kippa-Ring station\r\n");
    expect(calendar).not.toMatch(/private|TZID|VTIMEZONE/i);
  }
});

it.each([
  "unknown",
  "2026-10-26T07:45:00",
  "2026-02-29T07:45:00Z",
  "2026-10-26T24:00:00Z",
])("falls back when a sibling time is invalid (%s)", (invalidTime) => {
  const { hass, state, related } = journeyData();
  related.next_departure = { ...related.next_departure!, state: invalidTime };
  const payload = buildJourneySharePayload(state, related, hass);
  if (!payload.available || !payload.calendar.available)
    throw new Error("Calendar unavailable");
  expect(payload.calendar.data.start_date_time).toBe(
    "2026-10-26T07:39:00.000Z",
  );
});

it("keeps the share text when scheduled times are missing or out of order", () => {
  const { hass, state, related } = journeyData();
  const legs = state.attributes.legs as Row[];
  delete legs[0]!.departureTimeUtc;
  related.next_departure = {
    ...related.next_departure!,
    state: "2026-10-26T07:45:00",
  };
  const missing = buildJourneySharePayload(state, related, hass);
  expect(missing).toMatchObject({
    available: true,
    calendar: { available: false, reason: expect.stringContaining("requires") },
  });
  related.next_departure.state = related.arrival_time!.state;
  const unordered = buildJourneySharePayload(state, related, hass);
  expect(unordered).toMatchObject({
    available: true,
    calendar: { available: false, reason: expect.stringContaining("after") },
  });
});

it("escapes calendar text, folds by UTF-8 octets, and creates a stable UID", () => {
  const { hass, state, related } = journeyData();
  const transit = (state.attributes.legs as Row[])[1]!;
  transit.origin = "Harbour, Pier; \\north\n" + "🚆".repeat(40);
  transit.destination = "Public terminal";
  transit.destinationIsPublicStop = true;
  const payload = buildJourneySharePayload(state, related, hass);
  if (!payload.available || !payload.calendar.available)
    throw new Error("Calendar unavailable");
  const stamp = new Date("2026-10-01T00:00:00Z");
  const file = buildCalendarFile(payload.calendar, stamp);
  const lines = file.split("\r\n");
  expect(lines.slice(0, 2)).toEqual(["BEGIN:VCALENDAR", "VERSION:2.0"]);
  expect(lines).toContain("PRODID:-//Home Assistant Translink//Journey//EN");
  expect(lines).toContain("BEGIN:VEVENT");
  expect(lines).toContain("END:VEVENT");
  expect(lines.slice(-2)).toEqual(["END:VCALENDAR", ""]);
  const encoder = new TextEncoder();
  expect(lines.every((line) => encoder.encode(line).length <= 75)).toBe(true);
  expect(lines.some((line) => line.startsWith(" 🚆"))).toBe(true);
  expect(file.replaceAll("\r\n ", "")).toContain(
    "LOCATION:Harbour\\, Pier\\; \\\\north\\n" + "🚆".repeat(40),
  );
  const uid = /^UID:[^\r\n]+/m.exec(file)?.[0];
  expect(uid).toMatch(/@ha-translink$/);
  const second = buildJourneySharePayload(state, related, hass);
  if (!second.available || !second.calendar.available)
    throw new Error("Calendar unavailable");
  expect(buildCalendarFile(second.calendar, stamp)).toContain(uid!);
  related.next_departure = {
    ...related.next_departure!,
    state: "2026-10-26T07:45:00Z",
  };
  const changed = buildJourneySharePayload(state, related, hass);
  if (!changed.available || !changed.calendar.available)
    throw new Error("Calendar unavailable");
  expect(buildCalendarFile(changed.calendar, stamp)).not.toContain(uid!);
});

it("uses only a verified public timetable URL grammar", () => {
  const base = "https://jp.translink.com.au/plan-your-journey/timetables/trip/";
  const valid = base + "s_T_RPSP_8_20261026_39766414";
  expect(validateTimetableUrl(valid)).toBe(valid);
  for (const invalid of [
    valid.replace("https:", "http:"),
    valid.replace("jp.translink", "example.translink"),
    valid.replace("jp.translink", "user:pass@jp.translink"),
    valid.replace("jp.translink", "@jp.translink"),
    valid + "?token=secret",
    valid + "?",
    valid + "#id",
    valid + "#",
    valid + "/extra",
    valid + "%2Fextra",
    base + "segment/../valid",
    base + "x".repeat(129),
    "not a url",
    null,
  ])
    expect(validateTimetableUrl(invalid)).toBeUndefined();
});
