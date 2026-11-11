# Public journey planner routing options

Research date: 11 November 2026. This note records the public contract checked for
[#54](https://github.com/tinkerologie/ha-translink/issues/54). The findings cover
the captured public website and feeds. The Android app was inspected statically,
and Queensland app runtime behaviour remains unverified.

## Public request fields

Both captures used Python's default HTTPS context with certificate and hostname
verification enabled. The OpenSSL 4 default CA store
(`/opt/homebrew/etc/openssl@4/cert.pem` on the capture host) held 181 trusted CA
certificates. Both requests completed with HTTP 200 and successful TLS
verification.

| Capture | UTC timestamp | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| [Planner HTML](https://jp.translink.com.au/plan-your-journey/journey-planner) | `2026-11-11T02:24:08.217722Z` | 158,645 | `c7f86d893e5c835cfec2b5d88847e06736d591548fe15607dbfc7944ebf36af9` |
| [Linked planner bundle](https://jp.translink.com.au/_next/static/chunks/app/%5Blocale%5D/plan-your-journey/journey-planner/page-9b68e94c381447b2.js) | `2026-11-11T02:24:08.420678Z` | 64,151 | `a6f0fdfa5bec2643691f9017e7c113d6ae4a990cee9bf697ecb95f4f7fb63b7f` |

- HTML headers: `Date: Wed, 11 Nov 2026 02:24:07 GMT` and
  `Cache-Control: private, no-cache, no-store, max-age=0, must-revalidate`.
- Bundle headers: `Date: Wed, 11 Nov 2026 02:24:08 GMT`,
  `Cache-Control: public, max-age=3600`, `ETag: W/"fa97-1a078546d10"`, and
  `Last-Modified: Sun, 06 Sep 2026 20:06:34 GMT`.

The bundle appends these form fields in order:
`searchDate`, `searchTime`, `startLocationId`, `start`, `endLocationId`,
`end`, `timeSearchMode`, `maximumWalkingDistance`, optional
`hafasJourneyPlanToggle`, `walkingSpeed`, repeated `fareTypes`, repeated
`serviceTypes`, and repeated `transportModes`. The integration's existing
serializer sends the repeated groups in the order `transportModes`,
`serviceTypes`, `fareTypes`. The optional site toggle is absent from the
integration's request. The tests pin the integration's existing body, headers,
and request ID. [Translink journey planning help](https://translink.com.au/plan-your-journey/journey-planning-help)

## Via stop

**Public request field unverified.** The authenticated web serializer has no
via field. The public help describes an origin and destination and documents
advanced options for modes, walking, service types, and fares. The official app
guide documents adding a stop, and the Play listing concerns the Android app.
These sources describe app behaviour. The resource `nxt_a11y_button_add_via`
is app-only evidence from the static inspection in the issue.
[Planner bundle](https://jp.translink.com.au/_next/static/chunks/app/%5Blocale%5D/plan-your-journey/journey-planner/page-9b68e94c381447b2.js) ·
[Planner help](https://translink.com.au/plan-your-journey/journey-planning-help) ·
[App guide](https://translink.com.au/plan-your-journey/translink-app/translink-app-features#journey-planning) ·
[Google Play](https://play.google.com/store/apps/details?id=de.hafas.android.translink)

The issue records a signed Android build `3.1.6 (2779)` for package
`de.hafas.android.translink`, base APK SHA-256
`eb1ef14983a396d1d7e780dc8bf00d25efec8ee816fe63f43a60cb51ecbf7cba`, and
REA evidence ID
`ev_fec95d1bc50f732eab07e413fedcf9ee99321fa87e6cab693ecaddecc4ee8e58`.
[Issue evidence](https://github.com/tinkerologie/ha-translink/issues/54)

For a 13:00 Brisbane Central-to-Milton request on 11 November (ID
`1538664711`, HTTP 200), the returned train listed Roma Street platform 8
(`SI:600029`) among its intermediate stops. The trip timetable
shows Central at 13:13, Roma Street at 13:15, then Milton at 13:18 Brisbane time.
This proves Roma Street is an ordered call on that returned itinerary. A
request that asks the public planner to route via Roma Street remains
unverified. [Public trip timetable](https://jp.translink.com.au/plan-your-journey/timetables/trip/s_T_RPSP_8_20261111_39764981) ·
[Calling-stop evidence](calling-stops-research.md)

## Maximum transfers

**Public request field unverified.** The app guide describes a transfer-count
preference. The web serializer has no such field. In the web results,
`numberOfTransfers` displays the itinerary's `transfers` value. The
five-minute rule in web help describes the time the planner allows for a
connection. [App guide](https://translink.com.au/plan-your-journey/translink-app/translink-app-features#journey-planning) ·
[Planner help](https://translink.com.au/plan-your-journey/journey-planning-help) ·
[Planner bundle](https://jp.translink.com.au/_next/static/chunks/app/%5Blocale%5D/plan-your-journey/journey-planner/page-9b68e94c381447b2.js)

The Central-to-Kippa-Ring CLI capture below returned `transfers: 0` for a direct
train and `transfers: 1` for train, walk to a different platform at Petrie,
then train. The older Kippa-Ring-to-Fortitude Valley fixture likewise contains
`0` and `1`. Every `sameVehicleContinuation` value in these captures was
`false`. The bundle's UI checks the flag on the outgoing leg and references
the next leg's route in its continuation message. The effect of a positive
flag on the upstream transfer count remains unverified. The HA Transfers
sensor currently calculates one fewer than the number of transit legs, with
a minimum of zero. [Retained planner fixture](../tests/fixtures/trip_page/plan_response_trip.json) ·
[GTFS linked trips](https://gtfs.org/documentation/schedule/reference/#linked-trips)

## Wheelchair and stroller routing

**Queensland routing support unverified in public sources.** The web serializer
has no wheelchair or stroller field, and the sampled itinerary, leg, and stop
objects had no accessibility data. The Android APK resource
`nxt_cp_dashboard_drop_down_wheelchair_stroller` is a resource-only hint.
Translink's rider guidance describes physical accessibility and boarding
conditions for prams and strollers. The sampled sources provide no
machine-readable stroller suitability data.
[Accessible services, stops and stations](https://translink.com.au/travel-with-us/accessibility/accessible-services) ·
[Prams and strollers](https://translink.com.au/travel-with-us/using-public-transport#prams-and-strollers)

The standard SEQ archive covers scheduled buses, trains, ferries, and trams.
The capture at `2026-11-11T02:31:08.049738Z` returned HTTP 200 with the same
verified default HTTPS configuration as above. The ZIP was 34,672,418 bytes,
SHA-256 `ec364b7bc51ae4d6de9becfe8a3ec009b9029f0ed761fce975b151bfdc1d9a07`,
with service dates from 10 November 2026 to 9 January 2027. The archive's
`stops.txt` (13,100 records) lacked `wheelchair_boarding`, and `trips.txt`
(128,674 records) lacked `wheelchair_accessible`. There were 833 rows with
`parent_station` references and no wheelchair boarding values to inherit.
The archive also lacked `pathways.txt` and `transfers.txt`.
[Translink open data catalogue](https://translink.com.au/about-translink/open-data) ·
[Standard SEQ GTFS ZIP](https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip)

The Cairns archive for the same service dates showed the same missing columns
and files, with 465 stops, 3,894 trips, and ZIP SHA-256
`71fa6aa0bfa67a8eac2214fc5e7f39480ae855f32dac9e983d9cb94f875f4398`.
A point-in-time GTFS-RT sample had no populated
`VehicleDescriptor.wheelchair_accessible` fields among 1,749 SEQ TripUpdate
and 1,050 SEQ VehiclePosition descriptors, and 63 Cairns TripUpdate and 37
Cairns VehiclePosition descriptors. The direct inspection covered the standard
SEQ and Cairns feeds. Future snapshots and other regions may have different
coverage. [Cairns GTFS ZIP](https://gtfsrt.api.translink.com.au/GTFS/CNS_GTFS.zip) ·
[GTFS-Realtime schema](https://gtfs.org/documentation/realtime/proto/)

The third-party GTFS Scorecard checked the school-inclusive SEQ feed on
10 November 2026. It reported unknown wheelchair boarding for all 17,254
stops and unknown trip accessibility for all 132,405 trips. This is dated
corroboration from a different archive. The school-inclusive ZIP was outside
our direct inspection. [GTFS Scorecard](https://gtfsscorecard.org/agency/translink-south-east-queensland/) ·
[Dated Scorecard artifact](https://gtfsscorecard.org/data/artifacts/translink-south-east-queensland/2026-11-10.json)

## Reproduce the checks

Fetch the public HTML and the observed bundle with TLS verification. When
checking a new deployment, take the planner bundle URL from the new HTML.

```sh
curl --fail --silent --show-error --max-time 20 --max-filesize 2097152 \
  --dump-header planner-html.headers --output planner.html \
  --write-out 'HTTP %{http_code}, TLS verify %{ssl_verify_result}\n' \
  'https://jp.translink.com.au/plan-your-journey/journey-planner'
curl --fail --silent --show-error --max-time 20 --max-filesize 2097152 \
  --dump-header planner-js.headers --output planner.js \
  --write-out 'HTTP %{http_code}, TLS verify %{ssl_verify_result}\n' \
  'https://jp.translink.com.au/_next/static/chunks/app/%5Blocale%5D/plan-your-journey/journey-planner/page-9b68e94c381447b2.js'
shasum -a 256 planner.html planner.js
grep -Eo 'n\.append\("[A-Za-z]+"' planner.js | uniq
```

Fetch the standard SEQ feed and inspect the relevant CSV headers and counts.

```sh
curl --fail --silent --show-error --max-time 45 --max-filesize 62914560 \
  --output SEQ_GTFS.zip \
  --write-out 'HTTP %{http_code}, TLS verify %{ssl_verify_result}, bytes %{size_download}\n' \
  'https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip'
python3 - <<'PY'
import csv
import hashlib
import io
from pathlib import Path
from zipfile import ZipFile

archive = Path("SEQ_GTFS.zip")
with archive.open("rb") as source:
    print(archive.stat().st_size, hashlib.file_digest(source, "sha256").hexdigest())

with ZipFile(archive) as feed:
    for name in ("feed_info.txt", "stops.txt", "trips.txt"):
        with feed.open(name) as source:
            rows = csv.DictReader(io.TextIOWrapper(source, encoding="utf-8-sig"))
            if name == "feed_info.txt":
                info = next(rows)
                print("service dates", info["feed_start_date"], info["feed_end_date"])
                continue
            fields = rows.fieldnames or []
            print(name, "wheelchair_boarding", "wheelchair_boarding" in fields)
            print(name, "wheelchair_accessible", "wheelchair_accessible" in fields)
            count = parents = 0
            for row in rows:
                count += 1
                parents += bool(row.get("parent_station"))
            print(name, "records", count, "parent_station references", parents)
    for name in ("pathways.txt", "transfers.txt"):
        print(name, name in feed.namelist())
PY
```

Run the opt-in capture from the repository using the integration development
environment. It sends a single request for the specified Brisbane wall time and
two known public station IDs. The output includes UTC capture time, URL,
computed ID, exact form body, HTTP status and the response text before model
validation.

```sh
./script/query-api --raw-plan 2026-11-11T13:00 ST:place_censta ST:place_kprsta
```

This command returned HTTP 200 at `2026-11-11T02:33:37.063582Z` with request
ID `1355966139`. Use a future Brisbane date and time to repeat the sample
after 11 November. Results vary with date, schedule and disruptions.

The following body is reconstructed from the 26 October Kippa-Ring-to-Fortitude
Valley fixture's `originalEnquiry` using the integration's field order. It
hashes to the captured request ID `1149538989`. The ID match corroborates the
reconstruction. The original request bytes were outside the retained fixture.
[Capture manifest](../tests/fixtures/trip_page/manifest.json)

```text
searchDate=2026-10-26&searchTime=5%3A21pm&startLocationId=ST%3Aplace_kprsta&start=Kippa-Ring+station&endLocationId=ST%3Aplace_forsta&end=Fortitude+Valley+station&timeSearchMode=LeaveAfter&maximumWalkingDistance=4000&walkingSpeed=Normal&transportModes=Train&serviceTypes=Express&serviceTypes=NightLink&serviceTypes=Regular&serviceTypes=School&fareTypes=Free&fareTypes=Prepaid&fareTypes=Standard
```

## Evidence required for implementation

- **Via stop.** Obtain the exact public input field from a source retrieved
  with verified TLS. Capture fixed-time baseline and constrained requests with
  exact encoded bodies and IDs. Verify the requested stop against the ordered
  `scheduled` calling-stop slice within leg bounds and define how a parent
  station matches platforms. An explicit realtime skip invalidates the match.
  Treat a missing stop in `realtime_partial` or `unavailable` calling data as
  indeterminate.
- **Transfer limit.** Capture responses with `sameVehicleContinuation: true`
  across adjacent transit legs and in a case with an intervening walk, recording
  the upstream `transfers` value for both. A local maximum would apply to the
  returned alternatives and use the same selection for timetable enrichment
  and journey summaries. Keep upstream-empty, local no-match and indeterminate
  outcomes distinct.
- **Accessibility.** Use explicit `wheelchair_boarding` with GTFS parent
  inheritance, trip `wheelchair_accessible`, and the relevant GTFS-RT vehicle
  descriptor. Represent the result as accessible, inaccessible, or unknown.
  Missing values and the absence of an `ACCESSIBILITY_ISSUE` notice leave access
  unknown. Stroller suitability requires its own explicit evidence.
  [GTFS Schedule reference](https://gtfs.org/documentation/schedule/reference/) ·
  [GTFS-Realtime schema](https://gtfs.org/documentation/realtime/proto/)
