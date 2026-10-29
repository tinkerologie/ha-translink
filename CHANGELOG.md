# Changelog

All notable changes to this project are documented in this file.

This project uses Home Assistant's calendar versioning scheme (`YYYY.M.P`, for example `2026.10.0`).

## [Unreleased]

### Fixed

- The release workflow retries `gh release verify` for about a minute, because GitHub writes the release attestation shortly after publishing. The 2026.10.6 run published correctly but failed this check. [#32](https://github.com/tinkerologie/ha-translink/issues/32)

## [2026.10.6] - 2026-10-29

### Fixed

- Journey planner, location search and nearby-stop requests that time out now raise a connection error, so a slow Translink response fails one refresh quietly and the next refresh recovers. Before, the timeout reached the catch-all handler, which logged "Unexpected error fetching Translink data" with a stack trace and an empty message. Timeouts on the optional real-time feeds (vehicle positions, trip updates and alerts) now leave that data empty for one refresh instead of failing it. Coordinator errors always name the exception type, so an exception with an empty message is still readable. [#26](https://github.com/tinkerologie/ha-translink/issues/26), [#27](https://github.com/tinkerologie/ha-translink/issues/27)
- The disruption event entity opts in to the in-place entity ID changes of Home Assistant 2026.11 (`async_entity_id_changed`), so renaming its entity ID no longer removes and re-adds it. The fallback ends in Home Assistant 2027.11.

### Added

- Releases ship the integration as `translink.zip`, with a `SHA256SUMS` file and a signed build provenance attestation. `hacs.json` sets `zip_release` and `filename`, so from this release HACS installs the zip and shows how many times the latest release's zip was downloaded. After this release, choosing an older release (one without the zip) in HACS can fail to download. `script/build_release_zip.py` builds the zip reproducibly from `SOURCE_DATE_EPOCH`, every pull request checks that two builds match byte for byte, and the release workflow uploads the assets to a draft before it publishes, so it works with immutable releases. The README describes manual installation from the zip and how to verify it. [#28](https://github.com/tinkerologie/ha-translink/issues/28)
- Deprecation checks for the current and the next Home Assistant release. [#29](https://github.com/tinkerologie/ha-translink/issues/29)
  - Blocking: pytest turns `DeprecationWarning` and `PendingDeprecationWarning` from the integration's own modules into errors, and fails a test when Home Assistant logs a deprecation report that names `translink` (`tests/deprecations.py`).
  - Early warning: the weekly `HA Next` workflow tests the newest Home Assistant on PyPI (betas included) and the head of Core's `dev` branch. It imports every module (`script/import_smoke.py`), runs the tests when a matching `pytest-homeassistant-custom-component` exists, and runs Hassfest. It opens one `ha-next` + `bug` issue per channel on failure and closes it when the channel passes again.
  - The weekly `HA Dev Blog` workflow (`script/ha_dev_blog.py`) reads the developer blog and opens one `ha-dev-blog` + `enhancement` issue per post that announces a change to code the integration uses.

### Changed

- Tests run against Home Assistant 2026.10.4 (was 2026.6.2), and `script/test` accepts `TEST_HOME_ASSISTANT_VERSION`, `TEST_PLUGIN_VERSION`, `TEST_PYTHON_VERSION` and `TEST_VENV_PATH` overrides.
- `script/hassfest` runs Hassfest from pinned Core source in an isolated `uv` environment, and supports Core 2026.11 and later, where the validator moved into `packages/hassfest`, and Core `dev`.
- Dashboard cards use Home Assistant's design tokens for spacing, typography, radii, focus rings, hover and warning fills, with fallbacks for older themes. The journey arrow mirrors in right-to-left languages and is hidden from screen readers.

## [2026.10.5] - 2026-10-26

### Added

- Bundled Journey, Departures and Service Alerts dashboard cards with native visual editors, automatic module registration, Home Assistant theme/locale support, responsive Sections sizing and keyboard-accessible details. Built with TypeScript 7 and tested at phone, tablet and desktop widths.
- Expandable per-leg calling-stop timelines sourced from verified public trip schedules, with separately matched GTFS-RT predictions and explicit partial/unavailable fallbacks. Timetable requests are bounded and cached; missing enrichment does not interrupt journey entities.

### Changed

- Publish CI coverage to Codecov and enforce the existing 100% Python line and branch coverage baseline. The OIDC upload runs in a separate job without executing project code.

- Register bundled cards through the HTTP/Lovelace setup lifecycle. The large live itinerary `legs` attribute is excluded from recorder history; entity IDs, states and configuration remain compatible.

- Pull requests get path labels and at most one type label, `bug` or `enhancement`, from the shared tinkerologie PR labeler. Dependabot pull requests whose largest update is a patch or minor version merge automatically once the checks and commit statuses on their head commit have finished without a failure (a Codecov check that is still pending is not waited for; a Codecov failure blocks); majors, and pull requests with open review threads, stay for review.
- Dependabot updates `uv.lock` (the `uv` ecosystem instead of `pip`), so version and security updates reach the lock file; `uv.lock` is refreshed to match `pyproject.toml`.
- Release workflows hardened (least-privilege job permissions, no expressions in shell scripts, no persisted checkout credentials, no dependency caches); scheduled workflows run on Australia/Brisbane time. New CI workflow runs lint and tests on every pull request. LICENSE now contains the complete Apache License 2.0 text.
- Workflow layout tidied after the release hardening (no behaviour change): `permissions:` blocks moved back to the top of their workflow or job in `release.yml`. `NOTICE` records the copyright holder.
- Tinkerologie-Bot governance report updated to v1.4.3: an older run can no longer post a stale report after a newer run passed. Workflow formatting tidied.
- Repository standardised to the tinkerologie layout (STANDARDS.md in tinkerologie/.github): workflows renamed to the standard set (CI, Validate, Release, PR Governance, ...), every action pinned to a commit SHA, shared Dependabot, `.editorconfig`, `.gitattributes` and `CODEOWNERS` files, and organization-wide labels and community files.
- Tinkerologie-Bot's comment is now a readable "Pull request checklist": each problem is a numbered heading with plain-English guidance and its items listed underneath, and report updates for a pull request are serialised so an older run can never overwrite a newer one.
- Contribution governance: issues without a `bug` or `enhancement` label are labeled automatically when their type can be determined (issues labeled `question`, `duplicate`, `invalid`, `wontfix`, or `no-type` are skipped), so CodeRabbit can plan them. Pull requests that conflict with the default branch are labeled, and their authors are notified in a comment. Stale issues and pull requests are labeled after 14 days without activity and closed 30 days later. PR governance now re-validates a human-authored, non-draft PR when a bot such as CodeRabbit edits its description, instead of skipping the check and reporting a pass, only maintainers with write access may use `None` instead of linking an issue, and a link to an issue that does not exist now fails the check.
- Tinkerologie-Bot now posts one comment on pull requests that fail PR governance, listing every problem to fix, and updates it once they are fixed. PR governance runs from the default branch's workflow (`pull_request_target`), so a pull request cannot change its own check.
- Update repository URLs and documentation references to tinkerologie organization.

### Fixed

- Collapse identical planner alternatives in the departures card while preserving distinct trip identities when supplied.
- Match planner and GTFS-RT trip records with route suffixes and service dates. This can correct previously missing reported delays and vehicle positions.
- Resolve two existing Mypy typing errors without changing protobuf values or journey status behavior.

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
