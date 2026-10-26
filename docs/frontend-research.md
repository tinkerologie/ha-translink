# Translink dashboard research

Research date: 26 October 2026. Sources checked with Exa and Tavily; technical conclusions below use first-party documentation. User screenshots are visual references, not instructions. No production image asset licence was established.

## Home Assistant card contract

- Use `ha-card` for the theme-aware card surface. Validate configuration in `setConfig`; receive state through `hass`; avoid redrawing for unrelated state changes; use HA formatters where available for localized entity names/states. Register ES modules. [Custom cards](https://contributors.home-assistant.io/frontend/custom-ui/card/).
- Implement both `getGridOptions()` and `getCardSize()`. Sections use 12 columns, 56px rows and 8px gaps; default columns should be 3, 6, 9, or 12. Variable departure/alert lists should have content-driven height, with a useful minimum width. Masonry height is measured in 50px units. [Sizing](https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/).
- Register discoverable metadata in `window.customCards`, provide `getStubConfig`, and offer a visual editor. Current docs support `getConfigForm()` schemas; established `getConfigElement()` remains supported and wins if both exist. Its editor dispatches a bubbling/composed `config-changed` event containing the entire new config. Only suggest cards for matching entities. [Card editor and picker](https://contributors.home-assistant.io/frontend/custom-ui/card-editor/).
- Each card should have one clear purpose, fit the Sections grid, expose only supported data/actions, and visibly distinguish unavailable states from empty results. Default entity interaction opens more-info. [Dashboard design](https://contributors.home-assistant.io/design/dashboards/).
- Use semantic theme tokens rather than hardcoded palette values. Preserve legacy user theme properties such as `--primary-text-color`, `--secondary-text-color`, `--card-background-color`, and `--primary-color`; `--ha-space-*` and `--ha-font-*` supply spacing/type tokens. Use logical CSS properties for RTL. [Theming](https://contributors.home-assistant.io/frontend/architecture/theming/). Home Assistant explicitly describes its frontend as mobile-first. [Frontend overview](https://developers.home-assistant.io/docs/frontend/).
- Register static assets with `await hass.http.async_register_static_paths([StaticPathConfig(...)])`; old synchronous `register_static_path` was removed after deprecation. [Async static paths](https://developers.home-assistant.io/blog/2024/06/18/async_register_static_paths/). Core's `add_extra_js_url` explicitly permits custom integrations to register extra JS/module URLs. [Core frontend source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/frontend/__init__.py).

## Accessibility implementation decisions

Use real buttons/links, descriptive labels, visible keyboard focus, native disclosure controls with expanded state, and no color-only delay/status meanings. WCAG 2.2 minimum target size is 24×24 CSS px subject to exceptions; aim for 44px controls as a more generous mobile design choice, not an HA-specific mandatory number. [Target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html), [Use of color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html).

Verify narrow widths, light/dark themes, keyboard navigation, large text, long stop names, unavailable/unknown data, no-service results, and invalid configuration. Respect reduced-motion preferences if adding animation. These are implementation/validation recommendations; no claim is made that the whole integration has certified WCAG compliance.

## TypeScript 7

Search indexes surfaced Microsoft's earlier TypeScript 7 Beta/native-preview articles. Those describe `@typescript/native-preview@beta` and `tsgo`, but are historical and do not establish today's package status. [Historical Beta announcement](https://devblogs.microsoft.com/visualstudio/typescript-7-beta-now-enabled-by-default-in-visual-studio-2026-18-6-insiders-3), [Native compiler usage](https://devblogs.microsoft.com/typescript/announcing-typescript-native-previews/).

Live verification of the current npm registry with `npm view` showed: stable `typescript` is **7.0.2**, while `@typescript/native-preview` is `7.0.0-dev.20260707.2`; all three local scaffold integrations already use TypeScript 7.0.2. Use and pin stable `typescript@7.0.2`. This live registry evidence supersedes the older indexed articles. [Official TypeScript package](https://www.npmjs.com/package/typescript).

## Translink design reference

The official app emphasizes departure lists, journey duration/disruption summaries, live tracking, and expandable journey information. It displays real-time offsets as signed minutes; `+0` indicates on time. Use this hierarchy as inspiration while following HA surfaces and theme controls. Do not label scheduled data as real-time or invent intermediate stops/maps if the integration does not have those data. [Translink app features](https://translink.com.au/plan-your-journey/translink-app/translink-app-features).

Candidate scope based on the request: Departures card (next departure, route/headsign, platform, time and realtime/scheduled status), Journey card (origin/destination, timing, duration, available leg detail), Alerts card (relevant disruptions with accessible expand/collapse and safe external source links). A live vehicle map requires actual location entities/coordinates; use the HA native map when available instead of fabricating app parity.

Official image references discovered by Tavily extraction:

- [Journey planning](https://translink.com.au/sites/default/files/styles/original/public/acquiadam-assets/Translink%20app_Journey%20planning.png?itok=nptQFmQd)
- [Alerts](https://translink.com.au/sites/default/files/styles/original/public/acquiadam-assets/Translink%20app_Alerts.png?itok=GKEp-PC9)
- [Departures](https://translink.com.au/sites/default/files/styles/original/public/acquiadam-assets/Translink%20app_Departures.png?itok=2LcSddav)
- [Map](https://translink.com.au/sites/default/files/styles/original/public/acquiadam-assets/Translink%20app_Maps.png?itok=aHXxcfUJ)
- [Real-time](https://translink.com.au/sites/default/files/styles/original/public/acquiadam-assets/Translink%20app_Real-time.png?itok=Zk9csZSH)
- [My Trips](https://translink.com.au/sites/default/files/styles/original/public/acquiadam-assets/Translink%20app_MyTrips.png?itok=-qQmO9Iw)
- [Live navigation](https://translink.com.au/sites/default/files/styles/original/public/acquiadam-assets/Translink%20app_Live%20navigation.png?itok=mwiB3uth)

These are references only. Production cards should use HA icons and local bundled code, not hotlink app screenshots or introduce a dependency on external image availability.

Search accounting: four Exa searches with five requested results each; Tavily searches and direct extraction also completed.



## Verified compatibility and integration design

The minimum supported HA release is 2025.9.0 (`hacs.json`); local Python tests use
2026.6.2, and the authorized test container reports 2026.10.4. The following APIs
were inspected in official source at both 2025.9.0 and 2026.6.2:

- HTTP exports `StaticPathConfig(url_path, path, cache_headers=True)` and awaited
  `hass.http.async_register_static_paths(configs)`. File hashing runs in HA's executor.
  [2025.9 source](https://github.com/home-assistant/core/blob/2025.9.0/homeassistant/components/http/__init__.py),
  [2026.6 source](https://github.com/home-assistant/core/blob/2026.6.2/homeassistant/components/http/__init__.py).
- `hass.data[LOVELACE_DATA]` is a `LovelaceData` object with `.resources`, not a
  dictionary. Storage resources are `ResourceStorageCollection`; YAML resources
  are `ResourceYAMLCollection`. `async_get_info()` ensures storage is loaded;
  `async_items()` returns `id`, `url`, `type`; create/update take `url`, `res_type`.
  Delete takes the resource ID. This internal API is isolated in `frontend.py`.
  [2025.9 Lovelace](https://github.com/home-assistant/core/blob/2025.9.0/homeassistant/components/lovelace/__init__.py),
  [2025.9 resources](https://github.com/home-assistant/core/blob/2025.9.0/homeassistant/components/lovelace/resources.py),
  [2026.6 resources](https://github.com/home-assistant/core/blob/2026.6.2/homeassistant/components/lovelace/resources.py).
- The frontend display registry exposes `entity_id`, `device_id`, `platform`,
  and `translation_key`, including in the minimum-version frontend. Cards group
  siblings through those fields rather than constructing entity IDs from names.
  [Frontend registry source](https://github.com/home-assistant/frontend/blob/20250903.3/src/data/entity_registry.ts).
- The native `getConfigForm()` schema interface supplies `schema`, `computeLabel`
  and `computeHelper`. This implementation uses native entity/boolean/number/text
  selectors. [Lovelace types](https://github.com/home-assistant/frontend/blob/dev/src/panels/lovelace/types.ts).

The existing local ha-unraid-management-agent, ha-unraid and ha-unifi-insights
projects supplied scaffold patterns for HA surfaces, picker registration, resource
cache busting and tests. Translink uses one deterministic bundle, a content hash,
integration-level setup and startup resource synchronization. It updates and
removes duplicate entries only for its own relative resource path. YAML dashboards
receive documented manual module registration; their resources are never changed.

Dates respect the user's HA language, time format and local/server time-zone
preference. Main journey and planner departure times are explicitly scheduled;
a summary delay is described as reported, and is never applied to every board row.
The separate calling-stop enhancement documents scheduled versus predicted stop
provenance in `calling-stops-research.md`.
