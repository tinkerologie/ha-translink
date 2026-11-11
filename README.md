# Translink Queensland Integration for Home Assistant

<!-- BADGES:START -->
[![Marketplace and HACS](https://img.shields.io/badge/Marketplace%20%7C%20HACS-Default-orange.svg)](https://www.hacs.xyz/docs/marketplace/)
[![GitHub Last Commit](https://img.shields.io/github/last-commit/tinkerologie/ha-translink)](https://github.com/tinkerologie/ha-translink/commits/main)
[![GitHub Release](https://img.shields.io/github/v/release/tinkerologie/ha-translink)](https://github.com/tinkerologie/ha-translink/releases)
[![codecov](https://codecov.io/gh/tinkerologie/ha-translink/graph/badge.svg)](https://codecov.io/gh/tinkerologie/ha-translink)
[![License](https://img.shields.io/github/license/tinkerologie/ha-translink)](./LICENSE)
<!-- BADGES:END -->

The **Translink Queensland** custom integration connects Home Assistant directly to the [Translink](https://translink.com.au/) public transport network across South East Queensland (Brisbane, Gold Coast, Sunshine Coast, Ipswich, Logan, Moreton Bay, Redlands) and regional Queensland centers.

The integration provides journey planning, vehicle tracking and stop timetables in Home Assistant.

- **Journey Planning & Commute Tracking**: Scheduled departures and arrivals, durations, transfers, platforms, Queensland 50c fares, and walking directions. Matched live feeds add predictions where available.
- **Live Vehicle GPS Tracking**: Real-time `device_tracker` entity powered by Translink's open GTFS-RT feeds, exposing live vehicle coordinates, bearing, and speed directly on Home Assistant maps.
- **Station & Stop Departure Boards**: Boardable departures across routes and directions from the selected station or platform. Rows show scheduled times and include expected times and service flags where Translink supplies them.
- **Disruptions & Service Alerts**: Journey planner notices, stop timetable notices and independent regional GTFS-RT service notices.

---

## Supported Services & Networks

- **South East Queensland (SEQ)**:
  - **Buses**: Brisbane City Council (BCC), Kinetic, Clarks, Transdev, Hornibrook, Thompson, Thompsons, Caboolture Bus Lines, and Surfside.
  - **Trains**: Queensland Rail Citytrain network (Airport, Beenleigh, Caboolture, Cleveland, Doomben, Ferny Grove, Ipswich/Rosewood, Kippa-Ring, Redcliffe, Shorncliffe, Springfield Central, and Gold Coast/Varsity Lakes lines).
  - **Ferries**: CityCat, CityHopper, and Cross River Ferries across the Brisbane River.
  - **Trams / Light Rail**: G:link (Gold Coast Light Rail).
- **Regional Queensland**:
  - Journey Planner mode supports regional urban networks (Cairns, Mackay, Toowoomba, Sunshine Coast, Bowen, etc.). Departure Board mode requires a station or platform with a public Translink timetable.

### Live data by region

| Journey feed | Coverage |
| --- | --- |
| South East Queensland | SEQ public trip updates and vehicle positions. |
| Cairns | CNS public trip updates and vehicle positions. Live matches require the same service date, route, trip, and boarding stop. |
| Schedule only | Planned times for journeys in other regions or for entries where you disable the live feed. |

Journey entries apply the selected feed to eligible legs only. A leg with a
different planner region uses scheduled times. Missing, malformed or stale feed
data leaves the schedule available. The **Delay** sensor shows `unknown` when
there is no applicable boarding prediction, and `0` for a measured zero delay.
See [Translink's open data feed table](https://translink.com.au/about-translink/open-data).

Departure and arrival boards use the timetable for the selected station or
platform, including in Cairns. Expected times appear when Translink provides
predictions in that timetable. Predictions can vary by stop and service.

---

## Installation

### Option 1: HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tinkerologie&repository=ha-translink&category=integration)

1. Open **HACS** in Home Assistant.
2. Select **Integrations** > Three dots in top right > **Custom repositories**.
3. Add `https://github.com/tinkerologie/ha-translink` with category **Integration**.
4. Click **Download**, then restart Home Assistant.
5. Go to **Settings > Devices & Services > Add Integration** and search for **Translink**.

### Option 2: Manual Installation

1. Download `translink.zip` from the latest release on the [Releases page](https://github.com/tinkerologie/ha-translink/releases).
2. Create the folder `config/custom_components/translink/` and extract the zip into it. `manifest.json` must end up directly in that folder.
3. Restart Home Assistant.
4. Go to **Settings > Devices & Services > Add Integration** and select **Translink**.

You can also copy the `custom_components/translink` directory from a clone of this repository into `config/custom_components/`.

#### Verify the download

Each release from 2026.10.6 onwards carries `translink.zip`, a `SHA256SUMS` file and a signed build provenance attestation. HACS installs the same zip. The "Downloaded N times" figure HACS shows is the download count of the latest release's zip, so it starts again with each release. To check that a zip you downloaded is the one the release workflow built:

```bash
gh attestation verify translink.zip -R tinkerologie/ha-translink
sha256sum -c SHA256SUMS
```

Keep `SHA256SUMS` in the same folder as the zip. On macOS, use `shasum -a 256 -c SHA256SUMS`.

After the first zip release, choosing an older release (one without the zip) in HACS can fail to download.

---

## Configuration

### Initial Setup (`Settings > Devices & Services > Add Integration > Translink`)

When adding the integration, select **Journey**, **Stop**, **Nearby stop** or **Service Notices**.

#### 1. Journey Mode (Commute Tracking)

| Field | Description | Example |
| --- | --- | --- |
| **Journey Name** | Friendly name for this journey device. | `Work Commute` |
| **Starting Point (Origin)** | Station name, bus stop name, landmark, or address. | `Central station` |
| **Destination** | Destination station name, bus stop name, landmark, or address. | `Springfield Central station` |
| **Transport Modes** | Public transport modes to include in journey routing. | `Bus`, `Ferry`, `Train`, `Tram` |
| **Live feed region** | Choose South East Queensland, Cairns, or Schedule only. | `Cairns` |
| **Enable Live Vehicle Tracking** | Create a live GPS `device_tracker` entity for the active transit vehicle. | `Enabled` |

When a search returns several matches, choose the intended location for each endpoint shown.

#### 2. Stop Mode (Departure Board)

| Field | Description | Example |
| --- | --- | --- |
| **Board Name** | Friendly name for the station or stop device. | `Roma Street Station` |
| **Station or Stop Name** | Station name, stop name, or stop number. | `Roma Street station` |
| **Transport Modes** | Transport modes to monitor from this stop. | `Train`, `Bus` |

Departure boards accept stations and stops. When several eligible matches appear, choose the station, stop, or platform you want to track.

#### 3. Nearby Stop Mode (Departure Board)

When adding a Translink entry, choose **Nearby stop (Departure Board)**, then select a Home Assistant zone or choose a point on the map. Confirm the exact stop ID from the nearby results, which show distances in metres and group platforms at the same station. The board shows departures across routes and directions from the selected stop's public Translink timetable.

Home Assistant sends the selected coordinates to Translink once per lookup and discards them afterwards. The entry saves the confirmed stop and your board preferences.

#### 4. Service Notices

Choose **South East Queensland (SEQ)** or **Cairns (CNS)** and a scope.

| Scope | Included notices |
| --- | --- |
| **Whole network** | All active and upcoming alerts in the selected feed, including notices with unknown scope. |
| **GTFS route** | Alerts for the selected GTFS route and agency-wide alerts. Enter a GTFS route ID such as `RPSP` or `RPSP-5154`. The base ID matches versioned IDs such as `RPSP-5154`. Passenger-facing route names and numbers may differ. |
| **Transport mode** | Alerts with an explicit GTFS `route_type` for Bus, Ferry, Train or Tram, plus agency-wide alerts. |

The Disruptions sensor counts matching notices and shows up to 20 notices. Each
notice includes up to 10 affected-entity selectors, 10 active periods and 1,024
description characters. The card shows omitted selector and period counts.
The sensor's `unclassified_count` reports alerts whose supplied scope could not
be determined for the selected filter. An empty selector is shown as unknown
scope. The regional Alerts feed is separate from Journey Planner disruptions
and the notices supplied by the selected station or platform timetable.

When the Alerts feed fails, the notice sensors and disruption event become
unavailable. The **Last Successful Fetch** diagnostic sensor keeps the last
successful refresh time. Its `feed_timestamp` attribute comes from Translink's
feed header.

### Reconfigure an entry

Choose **Reconfigure** from the Translink entry's menu to change locations or transport modes. For journeys, you can also change the live feed region. Existing journeys without a saved region use the SEQ feed only for legs the planner identifies as SEQ. Save **Reconfigure** to confirm a feed for that entry. Leave a location name as shown to keep its saved location. A departure board saved with a place or address searches again so you can choose a station or stop. A new search with several matches prompts you to choose a result. Reconfigure a Service Notices entry to update its name, network or scope.

### Integration Options (`Configure` button on the Translink entry)

Service Notices entries offer the update interval only.

| Option | Default | Description |
| --- | --- | --- |
| **Update Interval (seconds)** | `60` | Frequency for refreshing timetables and real-time feeds (between 30s and 600s). |
| **Time Search Mode** | `LeaveAfter` | Whether to calculate journeys leaving after current time (`LeaveAfter`) or arriving before (`ArriveBefore`). |
| **Walking Speed** | `Normal` | Walking speed preference (`Slow`, `Normal`, `Fast`). |
| **Maximum Walking Distance** | `4000` | Maximum acceptable walking distance in meters. |
| **Fare Preference** | `Adult` | Preferred go card fare tier to display (`Adult` or `Concession`). |
| **Enable Live Vehicle Tracking** | `true` | Toggle the live vehicle GPS device tracker entity. |

#### Journey planner limitations

Via stops, maximum transfers, and wheelchair or stroller routing are unavailable
in this integration because their public request contracts are unverified. The
Transfers sensor estimates vehicle changes from the returned legs, so a
through-service split across legs can count as a transfer. Accessibility
disruptions appear as notices. Step-free access is unknown when the available
data only shows that no notice was issued. [Routing research](docs/routing-options-research.md)

---

## Provided Entities

### Journey Entities

| Entity | Type | Details |
| --- | --- | --- |
| **Next Departure** | `sensor` (`timestamp`) | Scheduled departure in UTC, with `predicted_time` and `predicted_readable_time` when available. Other attributes include `origin`, `platform`, and `readable_time`. |
| **Arrival Time** | `sensor` (`timestamp`) | Scheduled arrival in UTC, with `predicted_time` and `predicted_readable_time` when available. Other attributes include `destination`, `platform`, and `readable_time`. |
| **Journey Duration** | `sensor` (`duration`, `min`) | Total journey travel time in minutes. |
| **Journey Status** | `sensor` (`enum`) | `scheduled`, `on_time`, `early`, `delayed`, `cancelled`, `boarding_skipped`, `departed`, `arrived`, or `no_service`. |
| **Next Service** | `sensor` | Line name and vehicle type (e.g. `T2 Springfield Central (Train)`). Attributes: `headsign`, `route_code`, `route_color`, `operator`, `trip_id`. |
| **Platform** | `sensor` | Starting platform or stand (e.g. `Platform 5`). |
| **Transfers** | `sensor` (`measurement`) | Number of transit vehicle changes required (e.g. `0`). |
| **Fare** | `sensor` (`monetary`, `AUD`) | Go Card transit fare (e.g. `$0.50` under Queensland 50c fares). Attributes: `fares_breakdown`. |
| **Delay** | `sensor` (`duration`, `min`) | Signed boarding delay in minutes. `unknown` when an applicable prediction is missing. |
| **Walking Distance** | `sensor` (`distance`, `m`) | Total walking distance in meters across journey legs. |
| **Disruptions** | `sensor` (`diagnostic`) | Count of planner notices, including during `no_service`. Each notice in `disruptions` has `leg` scope if referenced by the selected itinerary or `request` scope if returned as a top-level fallback. Notices expire at their timezone-aware end time. |
| **Itinerary** | `sensor` (`diagnostic`) | Journey legs, available timed calling stops with explicit schedule/prediction provenance, and route polyline. |
| **Live Vehicle** | `device_tracker` (`gps`) | Live vehicle GPS position, bearing, speed, and vehicle ID from GTFS Realtime feeds. |

### Stop Departure Board Entities

| Entity | Type | Details |
| --- | --- | --- |
| **Next Departure** | `sensor` (`timestamp`) | Scheduled timestamp for the first eligible upcoming visit, with `predicted_time` and `predicted_readable_time` when supplied. |
| **Next Service** | `sensor` | Next service line code and vehicle type. |
| **Platform** | `sensor` | Platform or bay for the next service. |
| **Delay** | `sensor` (`duration`, `min`) | Signed delay in minutes for the same visit as **Next Departure**, or `unknown` without a prediction offset. |
| **Disruptions** | `sensor` (`diagnostic`) | Current notices returned for the selected station or platform, including when the board has zero departures. |
| **Departures Board** | `sensor` (`diagnostic`) | Departure count, with `departures` and drop-off-only `arrivals` attributes from the selected stop timetable. Both lists include routes, directions, platforms and available prediction details. |

A platform board uses its platform response for notices. A station board uses
its station response. If the current notice section is unavailable, the board
retains the last valid notices until a later response supplies them. The live
`departures` attribute is available to cards and automations and excluded from
Recorder.

### Real-time status and delay automations

Before departure, Journey Status is `scheduled` when there is no applicable
boarding prediction. A live boarding offset of −1 rounded minute or less is
`early`. An offset of 3 rounded minutes or more is `delayed`. Other live offsets
are `on_time`. A cancelled transit leg sets `cancelled`, and a skipped first
boarding stop sets `boarding_skipped`. The status attributes include
`boarding_relationship` and `alighting_skipped`. When available, predicted
departure and arrival times determine the `departed` and `arrived` transitions.
Timestamp-triggered automations continue to use the scheduled sensor states.

When calculating journey status and delay, the integration ignores GTFS-RT updates
more than 300 seconds old or more than 60 seconds ahead of the current time. It
checks the trip update timestamp first and uses the feed timestamp when the trip
timestamp is absent. Predictions with no timestamp can still apply if they match
the selected visit.

Delay attributes include `delay_seconds`, `arrival_delay_seconds`,
`realtime_status`, `delay_source` and `realtime_updated_at`. Delay is negative
for an early boarding prediction, zero for a measured zero, and `unknown` without
an applicable boarding offset. Use this Home Assistant template when an
automation needs the previous nonnegative value:

```jinja
{% set value = states('sensor.daily_commute_delay') | int(0) %}
{{ [0, value] | max }}
```

---

## Dashboard cards

The integration bundles four cards and includes them in the HACS download.
After restarting Home Assistant, edit your dashboard and choose **Add card** →
**Translink Journey**, **Translink Departures**, **Translink Service Alerts** or
**Translink Journey Progress**.
Use each card's visual editor to choose the appropriate Translink sensor:

| Card | Entity to select | Options |
| --- | --- | --- |
| `custom:translink-journey-card` | Journey **Itinerary** sensor | `title`, `show_fare`, `legs_expanded`, `show_disruptions`, `show_planner` (default false), `alternatives_limit` (1–10, default 5), `show_actions` (default true), `calendar_entity` (optional) |
| `custom:translink-departures-card` | Stop **Departures board** sensor | `title`, `max_departures` (1–20, default 5), `show_platform`, `show_arrivals` (default false), `show_filters` (default false) |
| `custom:translink-progress-card` | Journey **Journey Progress** sensor | `title` |
| `custom:translink-alerts-card` | Journey, stop or Service Notices **Disruptions** count sensor | `title`, `max_alerts` (1–20, default 5) |

Cards find related sensors through Home Assistant's entity registry and device
identity, so renamed entity IDs are supported. They follow the dashboard theme,
locale/time preferences and Sections sizing. Journey details and alert descriptions
expand with keyboard-accessible controls. The stop timetable card shows
**Scheduled** and **Expected** times separately. It shows **Cancelled**,
**Skipped**, **Extra service**, **Boarding only** and platform changes when supplied
for that visit.
An empty board shows any current stop notices alongside the no-services
message. A reported delay belongs to the next-service summary.

Enable **Show Arrivals view** to switch between Departures and Arrivals. Arrivals
lists drop-off-only visits from the sensor's `arrivals` attribute. The timetable's
arrival-time semantics are unverified, so the card uses **Scheduled stop time**
and **Expected stop time**. An expected time appears only when supplied.

Enable **Show board filters** to filter the active view by route and direction.
Choose **Scheduled time** or **Route** order. Within each route, services appear in
scheduled-time order. The display limit applies after filtering in either view.

To show a regional notice scope, select the **Disruptions** sensor from its
Service Notices entry.

```yaml
type: custom:translink-alerts-card
entity: sensor.cairns_service_notices_disruptions
max_alerts: 10
```

Example for a Sections dashboard (replace these IDs with your actual entities):

```yaml
type: sections
path: transport
title: Transport
max_columns: 3
sections:
  - type: grid
    cards:
      - type: heading
        heading: Your journey
        icon: mdi:routes
      - type: custom:translink-journey-card
        entity: sensor.work_commute_itinerary
        legs_expanded: true
  - type: grid
    cards:
      - type: heading
        heading: Departures
        icon: mdi:train-bus
      - type: custom:translink-departures-card
        entity: sensor.central_station_departures_board
        max_departures: 5
  - type: grid
    cards:
      - type: heading
        heading: Service information
        icon: mdi:alert-circle-outline
      - type: custom:translink-alerts-card
        entity: sensor.work_commute_disruptions
```

Storage-mode dashboards receive one automatically managed module resource with a
content hash for cache busting. Other integrations' resources are left untouched.
For YAML resource mode, add this under your existing `lovelace.resources` list:

```yaml
- url: /translink_cards/translink-cards.js?v=1
  type: module
```

Increment `v` after updating the integration to refresh a manually registered
resource. If a card is missing, check **Settings → Dashboards → Resources**, verify
that the bundled file was copied with the integration, and refresh the browser.
The Journey card's optional planner calls a Home Assistant action. The cards get
all data through Home Assistant. The Journey card shows the active leg and the
provenance of its vehicle position. Use Home Assistant's native map card below to
see the live position.

Expand **Journey details** → **Calling stops** to see the supplied timetable.
Scheduled calling times remain separate from predicted times and reported delay.
All calling points include the boarding and alighting stops. If the schedule page
is unavailable, a matched feed-only list is labelled **Partial real-time list**;
passed stops can be missing. An unavailable list is omitted. Intermediate platform
values are not invented. Stop detail is public trip data cached by the integration;
page changes or missing upstream data may temporarily limit the timeline.

The itinerary `legs` attribute adds `callingStops`, `callingStopsSource` and
`callingStopsRealtimeUpdatedAt`; existing state values and entity IDs stay the same.
The large live `legs` payload is excluded from recorder history. See
[calling-stop data and provenance](docs/calling-stops-research.md) for field details.

Research, official app image references and compatibility evidence are in
[the frontend research note](docs/frontend-research.md).

---

## Plan a journey for a specific time

The response-only `translink.plan_journey` action uses a loaded journey's
origin, destination, transport modes and walking preferences to request a
schedule from Translink.

| Field | Accepted value | Default |
| --- | --- | --- |
| `entity_id` | Translink Journey **Itinerary** sensor | Required |
| `date` | Date in `YYYY-MM-DD` format | Required |
| `time` | Time in `HH:MM` or `HH:MM:SS` format | Required |
| `time_search_mode` | `LeaveAfter` or `ArriveBefore` | `LeaveAfter` |
| `sort_by` | `departure`, `arrival` or `duration` | `departure` |
| `limit` | Integer from 1 to 10 | 5 |

The action interprets `date` and `time` in `Australia/Brisbane`. Each call makes
one planner request and leaves the current sensors and polling schedule alone.

The response contains `sort_by`, `total_alternatives`, `returned`, `truncated`,
`alternatives` and `plan_notices`. Each alternative includes its zero-based
`planner_index`, `planner_first`, scheduled UTC `departure` and `arrival`,
`duration_mins`, `transfers`, compact scheduled `legs`, `legs_truncated` and
`notices`. `planner_first` identifies the planner's original first itinerary
for this request. Sorting may move it to another position, and sensors plan
on their own schedule. Missing schedule and duration values are `null`.
Transfers are estimated from the number of non-walking legs, minus one
with a minimum of zero. An itinerary with no legs has `null` transfers.

Departure sort breaks ties by arrival and duration. Arrival sort breaks ties by
departure and duration. Duration sort breaks ties by departure and arrival.
Each comparison puts missing values last and uses the original planner index
as its final tie-breaker. The action sorts before applying the limit. A search
with no journeys returns an empty alternatives list.

Each alternative contains up to 20 legs and up to 10 notices. Leg notices are
deduplicated and enriched from the planner details. `plan_notices` contains up
to 10 deduplicated notices whose IDs are unreferenced by all legs in the
planner response, including legs and alternatives beyond the result limits.

Use `response_variable` in a script or an automation action:

```yaml
- action: translink.plan_journey
  data:
    entity_id: sensor.work_commute_itinerary
    date: "2026-11-16"
    time: "08:30"
    time_search_mode: ArriveBefore
    sort_by: arrival
  response_variable: commute_plan
```

Enable **Show journey planner** (`show_planner: true`) in the Journey card to
use the Brisbane date and time picker. **Maximum alternatives**
(`alternatives_limit`) controls how many results appear. The card requests up
to 10 alternatives when you press **Plan**. Changing **Sort by** reorders
those results locally. Press **Plan** with the new sort order to search across
all upstream alternatives when the previous response was truncated.

### Sharing a journey or adding it to a calendar

Select **Share or export** on the Journey card to preview the text and calendar
fields. The preview includes scheduled times, modes, routes, verified trip links,
and public stop names and platforms. Walking legs appear as “Walk”. Private
endpoints, coordinates, polylines, fare, vehicle data, configuration names and
access tokens are excluded.

You can select the text manually, use **Share** or **Copy text** where supported,
or download a local `.ics` file. Set `calendar_entity` to a writable Home
Assistant calendar to enable **Add to Home Assistant calendar**. Calendar
exports use scheduled UTC instants and exclude realtime predictions. The
preview labels times in the dashboard's selected time zone.

Journey details show a **Trip timetable** link only after Translink's timetable
matches that leg. The links are date-specific. Set `show_actions: false` to
hide sharing, export and timetable controls.

## Journey progress

Add the **Translink Journey Progress** card and select the **Journey Progress**
sensor. The card shows the itinerary as a line of walking and transit legs and
highlights the active leg. Its next action shows where to board, transfer, or
alight, with scheduled or predicted timing when available.

Before departure, progress follows the first itinerary returned by the planner
(`tracking_basis: planner_first_itinerary`). At departure it retains the last
followed itinerary in memory (`pinned_itinerary`), even when the planner returns
a later service. This applies to a leading walk as well. The pin expires five
minutes after the later of the scheduled and matched predicted final arrival,
or when a cancellation is confirmed. A restart clears the pin.

The sensor reports whether the active leg comes from a vehicle observation
(`vehicle`), matched real-time timings (`realtime_schedule`), the timetable
(`schedule`), or insufficient evidence (`unknown`). This integration assumes
you follow the itinerary. It uses schedule and vehicle data without reading
rider location. The Home Assistant native map continues to show the vehicle
tracker, and the progress card uses a schematic without a route overlay.

With vehicle tracking enabled, the **Journey Transition** event entity reports
`transfer_stop_reached` and `alighting_stop_reached`. Two fresh observations
must show the same vehicle on the same trip, first before the target stop
sequence and then explicitly stopped at the confirmed stop and sequence.
These events describe the vehicle's arrival. If a polling interval misses the
stop, the feed is stale or ambiguous, or the visit is skipped or cancelled,
no event fires. Restored events are never fired again.

## Dashboard Examples

### 1. Commute Overview Tile & Entities Card

```yaml
type: vertical-stack
cards:
  - type: tile
    entity: sensor.daily_commute_next_departure
    name: Next Commute Train
    icon: mdi:train
    color: primary
  - type: entities
    title: Commute Details
    entities:
      - entity: sensor.daily_commute_next_service
        name: Service
      - entity: sensor.daily_commute_platform
        name: Platform
      - entity: sensor.daily_commute_status
        name: Status
      - entity: sensor.daily_commute_delay
        name: Delay
      - entity: sensor.daily_commute_arrival_time
        name: Estimated Arrival
      - entity: sensor.daily_commute_fare
        name: Fare
```

### 2. Live Vehicle Map Card

The tracker selects the first transit leg whose scheduled arrival has yet to pass.
An applicable real-time alighting prediction can extend that leg. Before boarding
it tracks the first service, during a transfer it tracks the next service, and
after the final transit leg it clears the active vehicle. A missing arrival time
keeps that leg active.

The vehicle must match the active trip and agree with the route and service date
when both feeds supply them. A live fix needs a vehicle timestamp that is at most
90 seconds old and no more than 30 seconds ahead of the current time. Positions
expire between updates. If multiple fresh vehicles match, the tracker clears the
position.

The `position_status` attribute is `live`, `stale`, `ambiguous`, `no_position`,
`no_active_leg`, or `disabled`. A missing timestamp is treated as stale. The
tracker publishes coordinates only while live and shows `unknown` without a live
fix. Turning off tracking removes the tracker entity.

Home Assistant's recorder excludes vehicle coordinates, accuracy, motion,
vehicle labels and IDs, position timestamps, and the list of matching zones.
Home Assistant can still record the tracker state, including the active zone name.
Diagnostics redact vehicle coordinates.

Display the live position on a native map card:

```yaml
type: map
title: Live Transit Vehicle Tracker
entities:
  - entity: device_tracker.daily_commute_live_vehicle
    name: Active Vehicle
default_zoom: 13
```

---

## Example Automations

### 1. Morning Commute Notification (15 Minutes Before Departure)

```yaml
automation:
  - alias: "Translink Commute Departure Reminder"
    trigger:
      - platform: time_pattern
        minutes: "/5"
    condition:
      - condition: time
        after: "06:30:00"
        before: "08:30:00"
      - condition: template
        value_template: >
          {% set dep = as_timestamp(states('sensor.daily_commute_next_departure'), none) %}
          {% if dep is not none %}
            {% set mins = ((dep - as_timestamp(now())) / 60) | int %}
            {{ mins <= 15 and mins > 10 }}
          {% else %}
            false
          {% endif %}
    action:
      - action: notify.notify
        data:
          title: "Translink Departure Reminder"
          message: >
            Your {{ states('sensor.daily_commute_next_service') }} departs from
            Platform {{ states('sensor.daily_commute_platform') }} in 15 minutes
            (Status: {{ states('sensor.daily_commute_status') }}).
```

### 2. Alert When Service is Delayed

```yaml
automation:
  - alias: "Translink Commute Delay Alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.daily_commute_delay
        above: 3
    action:
      - action: notify.notify
        data:
          title: "Translink Commute Delay"
          message: >
            {{ states('sensor.daily_commute_next_service') }} is running {{ states('sensor.daily_commute_delay') }} minutes late.
```

---

## Troubleshooting & Diagnostics

- **Public Open Data Feeds**: Translink journey planning and GTFS-Realtime feeds are open and do not require user credentials or API keys.
- **Vehicle Live Tracking Availability**: Vehicles appear on the live map when active in service and transmitting GTFS-RT coordinates. The tracker remains available with an unknown state until a current vehicle fix matches the active service.
- **Diagnostics**: You can download an anonymized diagnostics bundle from **Settings > Devices & Services > Translink > Download Diagnostics** to assist with bug reports.

---

## Removing the Integration

1. Go to **Settings > Devices & Services** and locate **Translink**.
2. Click the three-dot menu on the entry and select **Delete**.
3. If installed via HACS, open **HACS > Integrations > Translink > Remove** and restart Home Assistant.
