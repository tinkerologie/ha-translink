# Timed calling stops: Translink source research

Research date: 26 October 2026. Research only; no repository changes. Exa, Tavily, direct public HTTP reads and REA static analysis were used. Public server/client content was treated as data.

## Observed result

**The official trip timetable page provides actual ordered calling-stop names, IDs and scheduled UTC times.** It is a server-rendered HTML/Next.js Flight response, rather than a documented JSON trip endpoint. The page's trip ID matches `/api/plan` leg `tripId` exactly. This gives a verified source for intermediate scheduled times without interpolation.

1. `GET https://jp.translink.com.au/api/stop/timetable/kippa-ring-station` returns `id`, `name`, `position`, `stops`, `routes`, `departures`, `serviceAlerts`.
2. Its departure items contain `id`, `routeId`, `headsign`, `direction`, `scheduledDepartureUtc`, `departurePlatform`, `departureDescription`, `canBoardDebark`, and optional `realtime` (`expectedDepartureUtc`, `isExtra`, `isSkipped`, `isCancelled`).
3. The official stop page's client links each departure `id` to `/plan-your-journey/timetables/trip/{id}`. [Stop page](https://jp.translink.com.au/plan-your-journey/stops/kippa-ring-station).
4. The official trip HTML embeds a `trip` object with `id`, `headsign`, `path`, `route`, `departures`, `maxNoticeSeverity`, `serviceNotices`, `vehicle`, `hasRealtime`.
5. `trip.departures[]` contains `stopId`, `name`, `zone`, `position`, `order`, `scheduledDepartureUtc`, `canBoardDebark`, and `realtime`.

Verified sample page: [T2 Springfield Central trip](https://jp.translink.com.au/plan-your-journey/timetables/trip/s_T_RPSP_8_20261026_39766414). Its full route has 36 calling points. The first three observed times are:

| stopId | name | order | scheduledDepartureUtc |
| --- | --- | --- | --- |
| 600633 | Kippa-Ring station, platform 1, Kippa-Ring | 1 | 2026-10-26T07:46:00Z |
| 600635 | Rothwell station, platform 1, Rothwell | 2 | 2026-10-26T07:50:00Z |
| 600637 | Mango Hill East station, platform 1, Mango Hill | 3 | 2026-10-26T07:52:00Z |

The live `/api/plan` request for Kippa-Ring to Fortitude Valley returned that same trip ID, `origin.id=SI:600633`, `destination.id=SI:600010`, departure `07:46Z`, arrival `08:39Z`, `numberOfStops=19`. Slice the full trip by exact origin/destination stop IDs in correct sequence: this produces 20 calling points including endpoints, i.e. 19 intervals. Normalize only known `SI:` prefix differences for this matching.

**Important semantic observation:** the sample `/api/plan` leg's `skippedStops` contains Rothwell, Mango Hill East and the other 16 intermediate calls, all present in the full trip. It is therefore unsafe to interpret that field name as “the vehicle does not stop here.” It appears to mean stops omitted from the compact itinerary response, for this sample. A reliable UI should use trip timetable calls and explicit realtime skip flags instead of inventing express/pass-through semantics.

## Response extraction and limitations

The HTML includes inert `<script>` bodies containing `self.__next_f.push([1,"..."])`. Decode the JSON array to recover each string segment; concatenate segments in document order; use a JSON decoder to find objects under `"trip":` and accept only the one with an exact `id` match and a `departures` list. There is also a **translation dictionary** named `trip`, which must not be mistaken for the payload. Never evaluate scripts or use JavaScript execution to parse this data.

The selected train and a currently realtime bus timetable were sampled. Both trip pages returned `hasRealtime=false` and Flight's `"$undefined"` for per-stop `realtime`. Therefore this research **establishes scheduled times only**, not current per-stop prediction fields. The stop-board endpoint had live prediction fields, but those cannot be copied indiscriminately to other calling stops. Existing GTFS-RT stop updates may supplement explicitly matching trip/stop records; missing predictions must remain missing.

No documented JSON trip-detail endpoint was identified in official search results or the inspected trip client. TripTimetable consumes server-supplied props and contains no fetch call. This does not prove that no private/backend API exists. The HTML/Flight structure is an internal implementation detail and needs bounded response parsing, schema validation, timeout handling, caching and graceful fallback if used. Failed enrichment should not make otherwise valid journey entities unavailable. No extra runtime dependency is necessary for inert HTML/JSON parsing.

Prefer exact requested trip identity; restrict URLs to the known JP origin and escaped ID path; bound fetched bytes and call count; cache per trip/date; trim downstream output to the requested leg. Preserve the distinction between absent timetable data, no intermediate calls, and scheduled data without realtime. Loop routes require sequence/time-aware boundary selection, not a dictionary keyed only by stop ID.

## Read-only probe

The following fetches public journey data only. No credentials are needed:

```sh
curl --fail --max-time 20 \
  'https://jp.translink.com.au/api/stop/timetable/kippa-ring-station'
curl --fail --max-time 20 \
  'https://jp.translink.com.au/plan-your-journey/timetables/trip/s_T_RPSP_8_20261026_39766414'
```

Use a currently returned departure ID for a future run; sample IDs are date-specific. The existing repo client already knows the form/hash contract for the read-only planner POST. Verified search IDs: `ST:place_kprsta` and `ST:place_forsta`.

## Durable official alternative

Translink officially publishes GTFS schedules and GTFS Realtime, states that these data feed its own planner/app, and requires realtime to be combined with static schedules. A GTFS schedule store (`trips.txt`, `stop_times.txt`, `stops.txt`, service calendar) would avoid dependence on website HTML but introduces bulk download/storage/indexing scope. It should be a separately considered architectural choice rather than added silently. [Official open data](https://translink.com.au/about-translink/open-data), [SEQ schedule dataset](https://www.data.qld.gov.au/dataset/general-transit-feed-specification-gtfs-translink/resource/e43b6b9f-fc2b-4630-a7c9-86dd5483552b), [SEQ realtime updates](https://gtfsrt.api.translink.com.au/api/realtime/SEQ/TripUpdates).

## Implemented contract and limits

The accepted parser uses Python HTML/JSON decoding only. It handles literal Flight
push strings, byte-length text records split across pushes, JSON model records and
the anonymous `:HL` preload hints observed in complete live responses. It does not
execute JavaScript or resolve Flight references. Only one structurally valid trip
with the exact requested ID is accepted. Required schema references, malformed or
conflicting records, non-UTC times, ambiguous ordering and traversal/size bounds
fail closed. The dedicated exception derives from the existing
`TranslinkApiError` (the plan's `TranslinkError` name referred to this base).

The client uses HA's managed session and the existing JP host: escaped IDs up to
128 printable characters, no redirects, HTML 200 only, a 10-second timeout,
1 MiB decoded body limit and concurrency 2. The coordinator requests at most 4
unique trip pages per refresh, caches successes for 30 minutes and failures for
5 minutes, and retains at most 32 entries. These are chosen bounds with headroom,
not published upstream limits. Stop-mode refreshes make no trip-page requests.
A failed or changed page never makes an otherwise valid journey unavailable.

Each itinerary leg adds:

- `callingStops`: ordered stops including boarding and alighting endpoints.
  Fields: `order`, `stopId`, `name`, `platform`, `role`, `canBoardDebark`,
  `scheduledTimeUtc` and optional nested `realtime`.
- `callingStopsSource`: `scheduled`, `scheduled_with_realtime`,
  `realtime_partial`, or `unavailable`.
- `callingStopsRealtimeUpdatedAt`: the matching TripUpdate's timestamp, if used.

Scheduled values come directly from the trip page. The itinerary segment is
selected by exact stop IDs and endpoint times, including repeated stop visits.
The RT overlay requires matching trip identity, service date, route prefix and
stop occurrence; event time minus its explicit delay is used only to match the
schedule baseline, never to manufacture a displayed scheduled time. Explicit
SKIPPED/NO_DATA flags may match the same stop sequence/order. Missing or ambiguous
predictions stay absent. Signed delays, uncertainty and absent/zero values remain
distinct. The optional `realtime` object exposes the supplied arrival/departure
UTC times, delay seconds, uncertainty seconds, sequence and schedule relationship.

With no usable schedule, an unambiguous endpoint-matched GTFS-RT range can be
reported as `realtime_partial`; passed stops may be missing and scheduled times
remain null. Intermediate platforms are not supplied in the accepted schema and
remain null. Endpoint platforms come from the planner. `skippedStops` is retained
unchanged for compatibility; only an explicit RT relationship indicates a skipped
call. The itinerary sensor keeps its state and unique ID. `legs` are excluded
from recorder attributes to avoid recording a large timetable every refresh;
they remain available live to cards and automations.

Authentic planner and trimmed public trip/not-found HTML fixtures are retained in
`tests/fixtures/trip_page/`. Its manifest records capture timestamps, TLS
verification, URLs, HTTP metadata, original/retained hashes and sanitization.
Only relevant script pushes are retained unchanged, including text-record
framing; public maps/telemetry configuration is removed. Synthetic cases are
labelled in tests and cover formats and edge cases absent from those captures.

[GTFS-RT StopTimeUpdate and StopTimeEvent specification](https://gtfs.org/documentation/realtime/reference/#message-stoptimeupdate)
supports the explicit event fields and absence semantics. Route suffix and
zero-padded stop-ID normalization are observations from Translink's data, not
published universal GTFS rules.
