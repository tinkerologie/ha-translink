# Changelog

All notable changes to this project are documented in this file.

This project uses Home Assistant's calendar versioning scheme (`YYYY.M.P`, for example `2026.10.0`).

## [Unreleased]

### Added

### Changed

- Contribution governance: issues without a `bug` or `enhancement` label are labeled automatically so CodeRabbit can plan them, PRs that conflict with the default branch are labeled and their authors notified, and stale issues and PRs are closed (stale after 14 days, closed 30 days later). PR governance no longer passes silently when a bot edits the PR description.
- Update repository URLs and documentation references to tinkerologie organization.

### Fixed

## [2026.10.4] - 2026-10-08

### Added
- **Dynamic Transport Mode Icons for Map and Dashboard Entities**:
  - Live vehicle tracker (`device_tracker.<entry>_vehicle_tracker`) now renders transport-specific Material Design icons dynamically on the Home Assistant Map area and Map cards based on the active vehicle mode:
    - Train: `mdi:train`
    - Bus: `mdi:bus`
    - Ferry: `mdi:ferry`
    - Tram / Light Rail: `mdi:tram`
    - Fallback: `mdi:bus-marker`
  - Next Service sensor (`sensor.<entry>_next_service`) also dynamically adjusts its entity icon to match the mode of transport for the upcoming journey or departure.
- **Enhanced GTFS-Realtime Trip & Vehicle Correlation**:
  - Fixed cross-feed correlation between Journey Planner itinerary legs (which format trip identifiers as `s_T_<service>_<dir>_<date>_<trip_id>`) and GTFS-RT `VehiclePositions` and `TripUpdates` feeds (which format trip identifiers as `<trip_id>-<agency>...`).
  - Extracted and indexed normalized base trip IDs across feeds, allowing real-time GPS locations, speed, bearing, and live arrival delays to accurately track trains, buses, ferries, and trams in real time on the Map.

### Changed

- Update repository URLs and documentation references to tinkerologie organization.
- **Home Assistant 2026.10 Compatibility & Standards**:
  - Modernized platform setup entry signatures across all entity platforms (`device_tracker`, `sensor`, `event`, and `diagnostics`) with `TranslinkConfigEntry` type annotations.
  - Aligned `TrackerEntity` location accuracy reporting to use `float` values (`15.0`) in accordance with the latest Home Assistant core specifications.
  - Added `route_color` attribute to `device_tracker` extra state attributes to support custom card rendering and map track styling.

## [2026.10.3] - 2026-10-06

### Changed

- Update repository URLs and documentation references to tinkerologie organization.
- **Brand Logos and Icons**:
  - Updated integration brand icons and logos (`icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`) to the official Translink 3-blade swirl emblem with high-resolution transparency.

## [2026.10.2] - 2026-10-06

### Fixed
- **Platform Sensor Icon**:
  - Replaced invalid non-existent icon string `mdi:train-car-platform` with valid Home Assistant core standard icon `mdi:bus-stop-uncovered`.
  - Added explicit `icon="mdi:bus-stop-uncovered"` attribute to `platform` entity descriptions in both Journey and Stop departure sensors.

## [2026.10.1] - 2026-10-06

### Added
- **Disruption Event Entity (`event.<entry>_disruption`)**:
  - Implements Home Assistant's native `event` entity platform (`EventEntity`) for service disruption alerts.
  - Fires `disruption` events containing full incident attributes (`title`, `description`, `cause`, `effect`, `severity`, `route`, and notice list) whenever disruptions are detected or updated.
  - Fires `cleared` events when service returns to normal, enabling instant automation triggers and smartphone push notifications.
- **Disruption Description Sensor (`sensor.<entry>_disruption_description`)**:
  - Diagnostic text sensor displaying the active disruption headline (or `Normal` when clear) directly on dashboards and glance cards.
  - Includes multi-line formatted summary and details in entity extra state attributes.
- **Enriched Disruption Sensor Attributes**:
  - `sensor.<entry>_disruptions` now provides `summary`, `description`, `latest_title`, `latest_description`, and structured disruption notice lists in addition to notice counts.
- **Comprehensive Notice Mapping**:
  - Added notice extraction and cross-referencing between itinerary legs and Translink notice feeds in `TranslinkApiClient`.

## [2026.10.0] - 2026-10-06

### Added
- **Initial release of Translink Queensland integration for Home Assistant (HACS)**.
- **Journey Planner Tracking**:
  - Real-time journey planning between any Origin and Destination in South East Queensland and regional networks.
  - Sensors for Next Departure timestamp, Arrival timestamp, Total Duration, Status, Transfers count, Next Route / Service, Origin Platform, Adult Go Card Fare (50c fares), Walking Distance, and Disruption Alerts count.
  - Rich journey attributes including full leg breakdown, intermediate/skipped stops, operator info, route hex color codes, and encoded polyline for map cards.
- **Live Vehicle GPS Tracking**:
  - `device_tracker` entity providing live vehicle location (latitude, longitude), bearing, speed, and vehicle ID from Translink's GTFS Realtime feeds.
- **Stop & Station Departure Boards**:
  - Dedicated Stop mode for tracking upcoming departures, platforms, and line delays for any Translink bus stop, train station, ferry terminal, or tram station.
- **Location Autocomplete & Geolocation Support**:
  - Dynamic station/stop search via Translink's search API in config and options flows.
- **Home Assistant Integration Quality Scale (Platinum)**:
  - Strict type checking, Pydantic v2 data models, async I/O with injected websession.
  - Complete translations (`strings.json`, `translations/en.json`) and icon definitions (`icons.json`).
  - Redacted diagnostics download support.
  - Robust test suite with comprehensive unit and integration tests.
