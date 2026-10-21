# Translink Queensland Integration for Home Assistant

<!-- BADGES:START -->
[![Marketplace and HACS](https://img.shields.io/badge/Marketplace%20%7C%20HACS-Default-orange.svg)](https://www.hacs.xyz/docs/marketplace/)
[![GitHub Last Commit](https://img.shields.io/github/last-commit/tinkerologie/ha-translink)](https://github.com/tinkerologie/ha-translink/commits/main)
[![GitHub Release](https://img.shields.io/github/v/release/tinkerologie/ha-translink)](https://github.com/tinkerologie/ha-translink/releases)
[![codecov](https://codecov.io/gh/tinkerologie/ha-translink/graph/badge.svg)](https://codecov.io/gh/tinkerologie/ha-translink)
[![License](https://img.shields.io/github/license/tinkerologie/ha-translink)](./LICENSE)
<!-- BADGES:END -->

The **Translink Queensland** custom integration connects Home Assistant directly to the [Translink](https://translink.com.au/) public transport network across South East Queensland (Brisbane, Gold Coast, Sunshine Coast, Ipswich, Logan, Moreton Bay, Redlands) and regional Queensland centers.

It brings the complete real-time experience of the official Translink app into Home Assistant:
- **Journey Planning & Commute Tracking**: Real-time departure times, arrival times, duration, transfer counts, origin/destination platforms, line colors, Queensland 50c fares, and walking directions between any Starting Point and Destination.
- **Live Vehicle GPS Tracking**: Real-time `device_tracker` entity powered by Translink's open GTFS-RT feeds, exposing live vehicle coordinates, bearing, and speed directly on Home Assistant maps.
- **Station & Stop Departure Boards**: Real-time upcoming service timetables and platform allocations for any bus stop, train station, ferry terminal, or tram station.
- **Disruptions & Service Alerts**: Live network disruption alerts and delay tracking.

---

## Supported Services & Networks

- **South East Queensland (SEQ)**:
  - **Buses**: Brisbane City Council (BCC), Kinetic, Clarks, Transdev, Hornibrook, Thompson, Thompsons, Caboolture Bus Lines, and Surfside.
  - **Trains**: Queensland Rail Citytrain network (Airport, Beenleigh, Caboolture, Cleveland, Doomben, Ferny Grove, Ipswich/Rosewood, Kippa-Ring, Redcliffe, Shorncliffe, Springfield Central, and Gold Coast/Varsity Lakes lines).
  - **Ferries**: CityCat, CityHopper, and Cross River Ferries across the Brisbane River.
  - **Trams / Light Rail**: G:link (Gold Coast Light Rail).
- **Regional Queensland**:
  - Journey Planner mode supports regional urban networks (Cairns, Mackay, Toowoomba, Sunshine Coast, Bowen, etc.). Departure Board mode is optimized for South East Queensland transit stations.

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

1. Copy the `custom_components/translink` directory into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings > Devices & Services > Add Integration** and select **Translink**.

---

## Configuration

### Initial Setup (`Settings > Devices & Services > Add Integration > Translink`)

When adding the integration, select whether you want to track a **Journey** or a **Stop**:

#### 1. Journey Mode (Commute Tracking)

| Field | Description | Example |
| --- | --- | --- |
| **Journey Name** | Friendly name for this journey device. | `Work Commute` |
| **Starting Point (Origin)** | Station name, bus stop name, or address. Translink's location search automatically matches stops. | `Central station` |
| **Destination** | Destination station name, bus stop name, or address. | `Springfield Central station` |
| **Transport Modes** | Public transport modes to include in journey routing. | `Bus`, `Ferry`, `Train`, `Tram` |
| **Enable Live Vehicle Tracking** | Create a live GPS `device_tracker` entity for the active transit vehicle. | `Enabled` |

#### 2. Stop Mode (Departure Board)

| Field | Description | Example |
| --- | --- | --- |
| **Board Name** | Friendly name for the station or stop device. | `Roma Street Station` |
| **Station or Stop Name** | Stop name or station search query. | `Roma Street station` |
| **Transport Modes** | Transport modes to monitor from this stop. | `Train`, `Bus` |

### Integration Options (`Configure` button on the Translink entry)

| Option | Default | Description |
| --- | --- | --- |
| **Update Interval (seconds)** | `60` | Frequency for refreshing timetables and real-time feeds (between 30s and 600s). |
| **Time Search Mode** | `LeaveAfter` | Whether to calculate journeys leaving after current time (`LeaveAfter`) or arriving before (`ArriveBefore`). |
| **Walking Speed** | `Normal` | Walking speed preference (`Slow`, `Normal`, `Fast`). |
| **Maximum Walking Distance** | `4000` | Maximum acceptable walking distance in meters. |
| **Fare Preference** | `Adult` | Preferred go card fare tier to display (`Adult` or `Concession`). |
| **Enable Live Vehicle Tracking** | `true` | Toggle the live vehicle GPS device tracker entity. |

---

## Provided Entities

### Journey Entities

| Entity | Type | Details |
| --- | --- | --- |
| **Next Departure** | `sensor` (`timestamp`) | UTC departure timestamp. Attributes: `origin`, `platform`, `readable_time` (e.g. `09:43 AM`). |
| **Arrival Time** | `sensor` (`timestamp`) | UTC destination arrival timestamp. Attributes: `destination`, `platform`, `readable_time`. |
| **Journey Duration** | `sensor` (`duration`, `min`) | Total journey travel time in minutes. |
| **Journey Status** | `sensor` (`enum`) | `scheduled`, `on_time`, `delayed`, `departed`, `arrived`, or `no_service`. |
| **Next Service** | `sensor` | Line name and vehicle type (e.g. `T2 Springfield Central (Train)`). Attributes: `headsign`, `route_code`, `route_color`, `operator`, `trip_id`. |
| **Platform** | `sensor` | Starting platform or stand (e.g. `Platform 5`). |
| **Transfers** | `sensor` (`measurement`) | Number of transit vehicle changes required (e.g. `0`). |
| **Fare** | `sensor` (`monetary`, `AUD`) | Go Card transit fare (e.g. `$0.50` under Queensland 50c fares). Attributes: `fares_breakdown`. |
| **Delay** | `sensor` (`duration`, `min`) | Real-time vehicle delay in minutes compared to schedule. |
| **Walking Distance** | `sensor` (`distance`, `m`) | Total walking distance in meters across journey legs. |
| **Disruptions** | `sensor` (`diagnostic`) | Active disruption notices count. Attributes: `disruptions` details. |
| **Itinerary** | `sensor` (`diagnostic`) | Complete multi-leg journey breakdown with intermediate stops, skipped stops, and Google polyline. |
| **Live Vehicle** | `device_tracker` (`gps`) | Live vehicle GPS position, bearing, speed, and vehicle ID from GTFS Realtime feeds. |

### Stop Departure Board Entities

| Entity | Type | Details |
| --- | --- | --- |
| **Next Departure** | `sensor` (`timestamp`) | Next scheduled or real-time departure from this stop. |
| **Next Service** | `sensor` | Next service line code and vehicle type. |
| **Platform** | `sensor` | Platform or bay for the next service. |
| **Delay** | `sensor` (`duration`, `min`) | Line delay in minutes. |
| **Disruptions** | `sensor` (`diagnostic`) | Disruption notices affecting this stop. |
| **Departures Board** | `sensor` (`diagnostic`) | Full upcoming departures list with routes, times, and destinations. |

---

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

Display the active train, bus, or ferry in real time as it moves toward your destination:

```yaml
type: map
title: Live Transit Vehicle Tracker
entities:
  - entity: device_tracker.daily_commute_live_vehicle
    name: Active Vehicle
hours_to_show: 1
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
- **Vehicle Live Tracking Availability**: Vehicles appear on the live map when active in service and transmitting GTFS-RT coordinates. If a vehicle has not yet begun its scheduled run, the entity remains available with the platform's station coordinates until live tracking commences.
- **Diagnostics**: You can download an anonymized diagnostics bundle from **Settings > Devices & Services > Translink > Download Diagnostics** to assist with bug reports.

---

## Removing the Integration

1. Go to **Settings > Devices & Services** and locate **Translink**.
2. Click the three-dot menu on the entry and select **Delete**.
3. If installed via HACS, open **HACS > Integrations > Translink > Remove** and restart Home Assistant.
