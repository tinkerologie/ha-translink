"""Config flow for Translink Queensland integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pydantic import ConfigDict

from .api.client import nearby_coordinates, plan_matches_realtime_region
from .api.models import NearbyStop
from .client import (
    AlertFeedError,
    LocationSearchResult,
    TranslinkApiError,
    TranslinkClient,
)
from .const import (
    ALERT_NETWORK_NAMES,
    AVAILABLE_FARE_PREFERENCES,
    AVAILABLE_TIME_SEARCH_MODES,
    AVAILABLE_TRANSPORT_MODES,
    AVAILABLE_WALKING_SPEEDS,
    CONF_END_LOCATION_ID,
    CONF_END_NAME,
    CONF_FARE_PREFERENCE,
    CONF_MAX_WALKING_DISTANCE,
    CONF_MODE,
    CONF_NAME,
    CONF_NOTICE_NETWORK,
    CONF_NOTICE_ROUTE_ID,
    CONF_NOTICE_ROUTE_MODE,
    CONF_NOTICE_SCOPE,
    CONF_REALTIME_REGION,
    CONF_SCAN_INTERVAL,
    CONF_START_LOCATION_ID,
    CONF_START_NAME,
    CONF_STOP_LOCATION_ID,
    CONF_STOP_NAME,
    CONF_TIME_SEARCH_MODE,
    CONF_TRACK_VEHICLE,
    CONF_TRANSPORT_MODES,
    CONF_WALKING_SPEED,
    CONF_WINDOW_DATE,
    CONF_WINDOW_END,
    CONF_WINDOW_KIND,
    CONF_WINDOW_START,
    CONF_WINDOW_WEEKDAYS,
    DEFAULT_FARE_PREFERENCE,
    DEFAULT_MAX_WALKING_DISTANCE,
    DEFAULT_REALTIME_REGION,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIME_SEARCH_MODE,
    DEFAULT_TRACK_VEHICLE,
    DEFAULT_TRANSPORT_MODES,
    DEFAULT_WALKING_SPEED,
    DOMAIN,
    LOCATION_STOP_PREFIX,
    MIN_SCAN_INTERVAL,
    MODE_JOURNEY,
    MODE_NOTICES,
    MODE_STOP,
    MODE_WINDOW,
    NOTICE_ROUTE_ID_LIMIT,
    NOTICE_ROUTE_TYPES,
    REALTIME_REGION_NONE,
    SETUP_NEARBY_STOP,
    WINDOW_ONCE,
    WINDOW_OPTION_LIMITS,
    WINDOW_RECURRING,
    resolve_realtime_region,
)
from .window_schedule import WindowSchedule

_LOGGER = logging.getLogger(__name__)

_LOCATION_FIELDS = {
    **dict.fromkeys(
        (MODE_JOURNEY, MODE_WINDOW),
        (
            (CONF_START_LOCATION_ID, CONF_START_NAME, "start_query"),
            (CONF_END_LOCATION_ID, CONF_END_NAME, "end_query"),
        ),
    ),
    MODE_STOP: ((CONF_STOP_LOCATION_ID, CONF_STOP_NAME, "stop_query"),),
}
_RECONFIGURED_OPTIONS = {
    CONF_START_LOCATION_ID,
    CONF_START_NAME,
    CONF_END_LOCATION_ID,
    CONF_END_NAME,
    CONF_TRANSPORT_MODES,
}
_WINDOW_SCHEDULE_FIELDS = (
    CONF_WINDOW_KIND,
    CONF_WINDOW_DATE,
    CONF_WINDOW_WEEKDAYS,
    CONF_WINDOW_START,
    CONF_WINDOW_END,
)
_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_LOCATION_LABELS = {
    "station": "Station",
    "place": "Place or address",
    "unknown": "Location",
}
# Selector translation keys are lowercase. Entry data uses the canonical mode name.
_NOTICE_ROUTE_MODE_OPTIONS = {mode.lower(): mode for mode in NOTICE_ROUTE_TYPES}


def _realtime_region_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=region, label=label)
                for region, label in {
                    **ALERT_NETWORK_NAMES,
                    REALTIME_REGION_NONE: "Schedule only",
                }.items()
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


class _NearbyStopMatch(LocationSearchResult):
    """Adapt a nearby stop to the shared location picker."""

    model_config = ConfigDict(str_strip_whitespace=False)
    label: str


class _NearbyLocationSelector(selector.LocationSelector):
    """Keep the map widget and allow the flow to report invalid points."""

    def __call__(self, data: Any) -> dict[str, float]:
        """Validate the raw point before numeric coercion."""
        if (coordinates := _coordinates_from_mapping(data)) is None:
            return {}
        lat, lng = coordinates
        return {ATTR_LATITUDE: lat, ATTR_LONGITUDE: lng}


def _coordinates_from_mapping(value: object) -> tuple[float, float] | None:
    """Resolve coordinates from a map selection or zone state attributes."""
    if not isinstance(value, Mapping):
        return None
    return nearby_coordinates(value.get(ATTR_LATITUDE), value.get(ATTR_LONGITUDE))


def _zone_coordinates(hass: HomeAssistant, zone_id: str) -> tuple[float, float] | None:
    """Resolve the selected zone's current coordinates."""
    state = hass.states.get(zone_id)
    return _coordinates_from_mapping(state.attributes) if state is not None else None


def _nearby_candidates(stops: list[NearbyStop]) -> dict[str, LocationSearchResult]:
    """Group platforms by station, ordering groups by their closest platform."""
    groups: dict[tuple[str, str], list[NearbyStop]] = {}
    for stop in sorted(stops, key=lambda stop: (stop.distanceM, stop.id)):
        if not stop.id.startswith(LOCATION_STOP_PREFIX):
            continue
        group = ("station", stop.station.id) if stop.station else ("stop", stop.id)
        groups.setdefault(group, []).append(stop)

    matches: list[LocationSearchResult] = [
        _NearbyStopMatch(
            LocationId=stop.id,
            Description=stop.description,
            label=(f"{stop.station.name} — " if stop.station else "")
            + f"{stop.description} · {stop.id} · {stop.distanceM:g} m",
        )
        for group_stops in groups.values()
        for stop in group_stops
    ]
    return _location_candidates(matches, MODE_STOP)


async def _async_lookup_nearby(
    hass: HomeAssistant, coordinates: tuple[float, float]
) -> dict[str, LocationSearchResult] | str:
    """Look up candidates and map failures without exposing the location."""
    try:
        client = TranslinkClient(session=async_get_clientsession(hass))
        stops = await client.find_nearby_stops(*coordinates)
        candidates = _nearby_candidates(stops)
    except AbortFlow:
        raise
    except TranslinkApiError:
        return "cannot_connect"
    except Exception as err:
        _LOGGER.warning(
            "Unexpected error finding nearby Translink stops (%s)", type(err).__name__
        )
        return "unknown"
    return candidates or "no_nearby_stops"


def _location_candidates(
    results: list[LocationSearchResult], mode: str
) -> dict[str, LocationSearchResult]:
    """Keep the first occurrence of each eligible ID in API order."""
    candidates: dict[str, LocationSearchResult] = {}
    for result in results:
        if mode != MODE_STOP or result.is_board_candidate:
            candidates.setdefault(result.id, result)
    return candidates


def _location_option(result: LocationSearchResult) -> selector.SelectOptionDict:
    """Describe a candidate while using its public ID as the value."""
    if isinstance(result, _NearbyStopMatch):
        return selector.SelectOptionDict(value=result.id, label=result.label)
    kind = result.kind
    suffix = (
        f"Stop {result.id.removeprefix(LOCATION_STOP_PREFIX)}"
        if kind == "stop"
        else _LOCATION_LABELS[kind]
    )
    return selector.SelectOptionDict(value=result.id, label=f"{result.name} — {suffix}")


def _location_selector(
    id_field: str,
    candidates: dict[str, LocationSearchResult],
    stored_id: str | None,
) -> tuple[vol.Required, selector.SelectSelector]:
    """Build a required selector and use the saved ID when it is a match."""
    field = (
        vol.Required(id_field, default=stored_id)
        if stored_id in candidates
        else vol.Required(id_field)
    )
    return field, selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[_location_option(result) for result in candidates.values()],
            mode=selector.SelectSelectorMode.LIST,
        )
    )


class TranslinkConfigFlow(  # pyright: ignore[reportGeneralTypeIssues, reportCallIssue]
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Handle a config flow for Translink Queensland."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._reconfigure_entry: config_entries.ConfigEntry | None = None
        self._pending_input: dict[str, Any] = {}
        self._queries: dict[str, str] = {}
        self._candidates: dict[str, dict[str, LocationSearchResult]] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> TranslinkOptionsFlowHandler:
        """Get the options flow for this handler."""
        return TranslinkOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial mode selection step."""
        if user_input is not None:
            mode = user_input.get(CONF_MODE, MODE_JOURNEY)
            if mode == MODE_JOURNEY:
                return await self.async_step_journey()
            if mode == MODE_NOTICES:
                return await self.async_step_notices()
            if mode == MODE_WINDOW:
                return await self.async_step_window()
            if mode == SETUP_NEARBY_STOP:
                return await self.async_step_nearby()
            return await self.async_step_stop()

        schema = vol.Schema(
            {
                vol.Required(CONF_MODE, default=MODE_JOURNEY): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=MODE_JOURNEY,
                                label="Journey (Origin to Destination)",
                            ),
                            selector.SelectOptionDict(
                                value=MODE_WINDOW,
                                label="Commute window",
                            ),
                            selector.SelectOptionDict(
                                value=MODE_STOP,
                                label="Stop / Station (Departure Board)",
                            ),
                            selector.SelectOptionDict(
                                value=SETUP_NEARBY_STOP,
                                label="Nearby stop (Departure Board)",
                            ),
                            selector.SelectOptionDict(
                                value=MODE_NOTICES, label="Service Notices"
                            ),
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_journey(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle configuring a Journey between origin and destination."""
        errors: dict[str, str] = {}

        if user_input is not None and (
            result := await self._async_search_locations(
                MODE_JOURNEY, user_input, errors
            )
        ):
            return result

        return self._show_journey_form(errors, user_input)

    def _show_journey_form(
        self, errors: dict[str, str], suggested: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Show journey settings, preserving a submission when retrying."""
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default="Daily Commute"
                ): selector.TextSelector(),
                vol.Required(CONF_START_NAME): selector.TextSelector(),
                vol.Required(CONF_END_NAME): selector.TextSelector(),
                vol.Required(
                    CONF_REALTIME_REGION, default=DEFAULT_REALTIME_REGION
                ): _realtime_region_selector(),
                vol.Required(
                    CONF_TRANSPORT_MODES, default=DEFAULT_TRANSPORT_MODES
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=AVAILABLE_TRANSPORT_MODES,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_TRACK_VEHICLE, default=DEFAULT_TRACK_VEHICLE
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="journey",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    async def async_step_window(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a one-off or recurring commute window."""
        return await self._async_window_form(user_input, reconfigure=False)

    async def async_step_window_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the existing window schedule and endpoints."""
        return await self._async_window_form(user_input, reconfigure=True)

    async def _async_window_form(
        self, user_input: dict[str, Any] | None, *, reconfigure: bool
    ) -> ConfigFlowResult:
        """Validate the schedule before resolving any endpoints."""
        errors: dict[str, str] = {}
        saved = self._reconfigure_entry.data if self._reconfigure_entry else {}
        if user_input is not None:
            try:
                schedule = WindowSchedule.from_config(user_input)
            except ValueError as err:
                errors["base"] = str(err)
            else:
                if schedule.once is not None and schedule.on(
                    schedule.once
                ).end <= datetime.now(UTC):
                    errors[CONF_WINDOW_DATE] = "window_date_expired"
                elif result := await self._async_search_locations(
                    MODE_WINDOW, user_input, errors
                ):
                    return result
            saved = {**saved, **user_input}

        fields: dict[vol.Marker, selector.Selector] = {
            vol.Required(key, default=saved.get(key, "")): selector.TextSelector()
            for key in (CONF_START_NAME, CONF_END_NAME)
        }
        if not reconfigure:
            fields[
                vol.Required(CONF_NAME, default=saved.get(CONF_NAME, "Commute window"))
            ] = selector.TextSelector()
        date_field = (
            vol.Optional(CONF_WINDOW_DATE, default=saved[CONF_WINDOW_DATE])
            if saved.get(CONF_WINDOW_DATE)
            else vol.Optional(CONF_WINDOW_DATE)
        )
        fields.update(
            {
                vol.Required(
                    CONF_TRANSPORT_MODES,
                    default=saved.get(CONF_TRANSPORT_MODES, DEFAULT_TRANSPORT_MODES),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=AVAILABLE_TRANSPORT_MODES,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_WINDOW_KIND,
                    default=saved.get(CONF_WINDOW_KIND, WINDOW_RECURRING),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=WINDOW_ONCE, label="One-off"
                            ),
                            selector.SelectOptionDict(
                                value=WINDOW_RECURRING, label="Recurring"
                            ),
                        ]
                    )
                ),
                date_field: selector.DateSelector(),
                vol.Optional(
                    CONF_WINDOW_WEEKDAYS, default=saved.get(CONF_WINDOW_WEEKDAYS, [])
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=str(index), label=day)
                            for index, day in enumerate(_WEEKDAYS)
                        ],
                        multiple=True,
                    )
                ),
                vol.Required(
                    CONF_WINDOW_START, default=saved.get(CONF_WINDOW_START, "07:30:00")
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_WINDOW_END, default=saved.get(CONF_WINDOW_END, "08:30:00")
                ): selector.TimeSelector(),
            }
        )
        return self.async_show_form(
            step_id="window_reconfigure" if reconfigure else "window",
            data_schema=vol.Schema(fields),
            errors=errors,
        )

    async def async_step_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle configuring a Stop/Station departure board."""
        errors: dict[str, str] = {}

        if user_input is not None and (
            result := await self._async_search_locations(MODE_STOP, user_input, errors)
        ):
            return result

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default="Station Board"
                ): selector.TextSelector(),
                vol.Required(CONF_STOP_NAME): selector.TextSelector(),
                vol.Required(
                    CONF_TRANSPORT_MODES, default=DEFAULT_TRANSPORT_MODES
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=AVAILABLE_TRANSPORT_MODES,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="stop", data_schema=schema, errors=errors)

    async def async_step_nearby(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to choose a location source."""
        return self.async_show_menu(
            step_id="nearby", menu_options=["nearby_zone", "nearby_point"]
        )

    async def async_step_nearby_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Find stops near an explicitly selected Home Assistant zone."""
        errors: dict[str, str] = {}
        if user_input is not None and (
            result := await self._async_prepare_nearby(
                _zone_coordinates(self.hass, user_input.get("zone", "")), "zone", errors
            )
        ):
            return result
        return self.async_show_form(
            step_id="nearby_zone",
            data_schema=vol.Schema(
                {
                    vol.Required("zone"): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="zone")
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_nearby_point(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Find stops near an explicitly selected map point."""
        errors: dict[str, str] = {}
        if user_input is not None and (
            result := await self._async_prepare_nearby(
                _coordinates_from_mapping(user_input.get("location")),
                "location",
                errors,
            )
        ):
            return result
        return self.async_show_form(
            step_id="nearby_point",
            data_schema=vol.Schema(
                {vol.Required("location"): _NearbyLocationSelector()}
            ),
            errors=errors,
        )

    async def _async_prepare_nearby(
        self,
        coordinates: tuple[float, float] | None,
        field: str,
        errors: dict[str, str],
    ) -> ConfigFlowResult | None:
        """Look up the location and retain only the options for confirmation."""
        if coordinates is None:
            errors[field] = "location_unavailable"
            return None
        candidates = await _async_lookup_nearby(self.hass, coordinates)
        if isinstance(candidates, str):
            errors["base"] = candidates
            return None
        self._candidates = {CONF_STOP_LOCATION_ID: candidates}
        return await self.async_step_nearby_select()

    async def async_step_notices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up regional service notices."""
        return await self._async_notices_form(user_input, None)

    async def async_step_notices_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change a notice entry's name, network or scope."""
        return await self._async_notices_form(user_input, self._get_reconfigure_entry())

    async def _async_notices_form(
        self,
        user_input: dict[str, Any] | None,
        entry: config_entries.ConfigEntry | None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = entry.data if entry else {}
        if user_input is not None:
            network = user_input[CONF_NOTICE_NETWORK]
            scope = user_input[CONF_NOTICE_SCOPE]
            name = user_input[CONF_NAME].strip() or "Service Notices"
            data = {
                key: value
                for key, value in current.items()
                if key not in {CONF_NOTICE_ROUTE_ID, CONF_NOTICE_ROUTE_MODE}
            }
            data.update(
                {
                    CONF_MODE: MODE_NOTICES,
                    CONF_NAME: name,
                    CONF_NOTICE_NETWORK: network,
                    CONF_NOTICE_SCOPE: scope,
                }
            )
            data.setdefault(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            unique_id = f"notices_{network}_{scope}"
            if scope == "route":
                route_id = user_input.get(CONF_NOTICE_ROUTE_ID, "").strip()
                if (
                    not route_id
                    or len(route_id) > NOTICE_ROUTE_ID_LIMIT
                    or not route_id.isprintable()
                ):
                    errors[CONF_NOTICE_ROUTE_ID] = "invalid_route_id"
                else:
                    data[CONF_NOTICE_ROUTE_ID] = route_id
                    unique_id += f"_{route_id}"
            elif scope == "mode":
                route_mode = _NOTICE_ROUTE_MODE_OPTIONS.get(
                    user_input.get(CONF_NOTICE_ROUTE_MODE, "")
                )
                if route_mode is None:
                    errors[CONF_NOTICE_ROUTE_MODE] = "notice_mode_required"
                else:
                    data[CONF_NOTICE_ROUTE_MODE] = route_mode
                    unique_id += f"_{route_mode}"

            if not errors:
                if entry is None or entry.unique_id != unique_id:
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                client = TranslinkClient(session=async_get_clientsession(self.hass))
                try:
                    await client.fetch_alert_feed(network)
                except AlertFeedError:
                    errors["base"] = "cannot_connect"
                    await self.async_set_unique_id(None)
                else:
                    if entry is None:
                        return self.async_create_entry(title=name, data=data)
                    if entry.update_listeners and (
                        update_and_abort := getattr(
                            self, "async_update_and_abort", None
                        )
                    ):
                        return update_and_abort(
                            entry, unique_id=unique_id, title=name, data=data
                        )
                    return self.async_update_reload_and_abort(
                        entry, unique_id=unique_id, title=name, data=data
                    )

        values = {**current, **(user_input or {})}
        mode_suggestion = values.get(CONF_NOTICE_ROUTE_MODE)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default=values.get(CONF_NAME, "Service Notices")
                ): selector.TextSelector(),
                vol.Required(
                    CONF_NOTICE_NETWORK, default=values.get(CONF_NOTICE_NETWORK, "SEQ")
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=network, label=label)
                            for network, label in ALERT_NETWORK_NAMES.items()
                        ],
                    )
                ),
                vol.Required(
                    CONF_NOTICE_SCOPE, default=values.get(CONF_NOTICE_SCOPE, "network")
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["network", "route", "mode"],
                        translation_key="notice_scope",
                    )
                ),
                vol.Optional(
                    CONF_NOTICE_ROUTE_ID,
                    description={"suggested_value": values.get(CONF_NOTICE_ROUTE_ID)},
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_NOTICE_ROUTE_MODE,
                    description={
                        "suggested_value": mode_suggestion.lower()
                        if mode_suggestion
                        else None
                    },
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(_NOTICE_ROUTE_MODE_OPTIONS),
                        translation_key="notice_route_mode",
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="notices_reconfigure" if entry else "notices",
            data_schema=schema,
            errors=errors,
        )

    async def _async_search_locations(
        self, mode: str, user_input: dict[str, Any], errors: dict[str, str]
    ) -> ConfigFlowResult | None:
        """Search for each location and ask for a choice when needed."""
        self._pending_input = user_input
        self._queries = {}
        self._candidates = {}

        try:
            client = TranslinkClient(session=async_get_clientsession(self.hass))
            for id_field, name_field, placeholder in _LOCATION_FIELDS[mode]:
                query = str(user_input.get(name_field, "")).strip()
                self._queries[placeholder] = query
                saved = self._saved_location(id_field, name_field, query, mode)
                results = (
                    [saved]
                    if saved is not None
                    else await client.search_locations(query)
                )
                candidates = _location_candidates(results, mode)
                if not candidates:
                    errors[name_field] = (
                        "no_board_location" if results else "location_not_found"
                    )
                self._candidates[id_field] = candidates
        except TranslinkApiError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error searching for Translink locations")
            errors["base"] = "unknown"

        if errors:
            return None
        if any(len(candidates) > 1 for candidates in self._candidates.values()):
            return await self._async_step_location_selection(mode, None)
        return await self._async_confirm_locations(mode, {}, errors)

    def _saved_location(
        self, id_field: str, name_field: str, query: str, mode: str
    ) -> LocationSearchResult | None:
        """Reuse an unchanged location if the stored ID still applies."""
        if self._reconfigure_entry is None:
            return None
        current_data = self._reconfigure_entry.data
        stored_id = current_data.get(id_field)
        if not stored_id or query != current_data.get(name_field):
            return None
        result = LocationSearchResult(LocationId=stored_id, Description=query)
        if mode == MODE_STOP and not result.is_board_candidate:
            return None
        return result

    async def async_step_journey_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the ambiguous journey endpoints."""
        return await self._async_step_location_selection(MODE_JOURNEY, user_input)

    async def async_step_window_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the ambiguous commute window endpoints."""
        return await self._async_step_location_selection(MODE_WINDOW, user_input)

    async def async_step_stop_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a stop or station from the search matches."""
        return await self._async_step_location_selection(MODE_STOP, user_input)

    async def async_step_nearby_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the exact nearby stop ID and board preferences."""
        return await self._async_step_location_selection(
            MODE_STOP, user_input, nearby=True
        )

    async def _async_step_location_selection(
        self, mode: str, user_input: dict[str, Any] | None, *, nearby: bool = False
    ) -> ConfigFlowResult:
        """Validate the submitted locations and commit the confirmed results."""
        errors: dict[str, str] = {}
        if nearby and user_input is not None:
            self._pending_input = {
                CONF_NAME: user_input.get(CONF_NAME, ""),
                CONF_TRANSPORT_MODES: user_input.get(
                    CONF_TRANSPORT_MODES, DEFAULT_TRANSPORT_MODES
                ),
            }
        if user_input is not None and (
            result := await self._async_confirm_locations(
                mode, user_input, errors, nearby=nearby
            )
        ):
            if nearby:
                self._candidates.clear()
            return result
        if errors.get("base") == "region_mismatch":
            return self._show_journey_form(errors, self._pending_input)
        return self._show_location_selection(mode, errors, nearby=nearby)

    def _show_location_selection(
        self,
        mode: str,
        errors: dict[str, str] | None = None,
        *,
        nearby: bool = False,
    ) -> ConfigFlowResult:
        """Show selectors for fields that require an explicit choice."""
        saved_data = self._reconfigure_entry.data if self._reconfigure_entry else {}
        fields: dict[vol.Required, selector.Selector] = dict(
            _location_selector(id_field, candidates, saved_data.get(id_field))
            for id_field, candidates in self._candidates.items()
            if nearby or len(candidates) > 1
        )
        if nearby:
            fields.update(
                {
                    vol.Required(
                        CONF_NAME, default="Station Board"
                    ): selector.TextSelector(),
                    vol.Required(
                        CONF_TRANSPORT_MODES, default=DEFAULT_TRANSPORT_MODES
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=AVAILABLE_TRANSPORT_MODES,
                            multiple=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            )
        return self.async_show_form(
            step_id="nearby_select" if nearby else f"{mode}_select",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders=self._queries,
        )

    async def _async_confirm_locations(
        self,
        mode: str,
        selection: dict[str, Any],
        errors: dict[str, str],
        *,
        nearby: bool = False,
    ) -> ConfigFlowResult | None:
        """Resolve single matches and confirm selections before saving locations."""
        locations: dict[str, LocationSearchResult] = {}
        for id_field, candidates in self._candidates.items():
            if len(candidates) == 1 and not nearby:
                locations[id_field] = next(iter(candidates.values()))
                continue
            selected_id = selection.get(id_field)
            if not isinstance(selected_id, str) or selected_id not in candidates:
                errors["base"] = "invalid_location_selection"
                return None
            locations[id_field] = candidates[selected_id]

        unique_id = "_".join((mode, *(result.id for result in locations.values())))
        data = {
            CONF_TRANSPORT_MODES: self._pending_input.get(
                CONF_TRANSPORT_MODES, DEFAULT_TRANSPORT_MODES
            ),
        }
        if mode == MODE_JOURNEY:
            data[CONF_REALTIME_REGION] = self._pending_input.get(
                CONF_REALTIME_REGION, DEFAULT_REALTIME_REGION
            )
        for id_field, name_field, _ in _LOCATION_FIELDS[mode]:
            data[id_field] = locations[id_field].id
            data[name_field] = locations[id_field].name

        if mode == MODE_WINDOW:
            schedule = WindowSchedule.from_config(self._pending_input)
            unique_id = f"{unique_id}_{schedule.identity}"
            data.update(
                {key: self._pending_input.get(key) for key in _WINDOW_SCHEDULE_FIELDS}
            )
            data[CONF_WINDOW_WEEKDAYS] = self._pending_input.get(
                CONF_WINDOW_WEEKDAYS, []
            )
            if schedule.once is None:
                data[CONF_WINDOW_DATE] = None
            else:
                data[CONF_WINDOW_WEEKDAYS] = []

        try:
            if self.source == config_entries.SOURCE_RECONFIGURE:
                return await self._async_finish_reconfigure(unique_id, data)
            return await self._async_finish_setup(mode, unique_id, data, errors)
        except AbortFlow:
            raise
        except TranslinkApiError:
            errors["base"] = "cannot_connect"
        except Exception as err:
            if nearby:
                _LOGGER.warning(
                    "Unexpected error confirming a nearby Translink stop (%s)",
                    type(err).__name__,
                )
            else:
                _LOGGER.exception("Unexpected error confirming Translink locations")
            errors["base"] = "unknown"
        await self.async_set_unique_id(None)
        return None

    async def _async_finish_setup(
        self,
        mode: str,
        unique_id: str,
        data: dict[str, Any],
        errors: dict[str, str],
    ) -> ConfigFlowResult | None:
        """Create a config entry from the confirmed locations."""
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        default_name = {
            MODE_JOURNEY: "Translink Journey",
            MODE_STOP: "Translink Stop",
            MODE_WINDOW: "Commute window",
        }[mode]
        name = str(self._pending_input.get(CONF_NAME, "")).strip() or default_name
        data.update(
            {
                CONF_MODE: mode,
                CONF_NAME: name,
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            }
        )
        if mode == MODE_WINDOW:
            return self.async_create_entry(title=name, data=data)

        client = TranslinkClient(session=async_get_clientsession(self.hass))
        if mode == MODE_JOURNEY:
            plan = await client.plan_journey(
                start_location_id=data[CONF_START_LOCATION_ID],
                start_name=data[CONF_START_NAME],
                end_location_id=data[CONF_END_LOCATION_ID],
                end_name=data[CONF_END_NAME],
                transport_modes=data[CONF_TRANSPORT_MODES],
            )
            if not plan_matches_realtime_region(plan, data[CONF_REALTIME_REGION]):
                errors["base"] = "region_mismatch"
                await self.async_set_unique_id(None)
                return None
            data.update(
                {
                    CONF_TRACK_VEHICLE: bool(
                        self._pending_input.get(
                            CONF_TRACK_VEHICLE, DEFAULT_TRACK_VEHICLE
                        )
                    ),
                    CONF_TIME_SEARCH_MODE: DEFAULT_TIME_SEARCH_MODE,
                    CONF_MAX_WALKING_DISTANCE: DEFAULT_MAX_WALKING_DISTANCE,
                    CONF_WALKING_SPEED: DEFAULT_WALKING_SPEED,
                    CONF_FARE_PREFERENCE: DEFAULT_FARE_PREFERENCE,
                }
            )
        else:
            await client.fetch_stop_timetable(data[CONF_STOP_LOCATION_ID])
        return self.async_create_entry(title=name, data=data)

    async def _async_finish_reconfigure(
        self, unique_id: str, data_updates: dict[str, Any]
    ) -> ConfigFlowResult:
        """Commit confirmed data, options and unique ID together."""
        entry = self._reconfigure_entry
        assert entry is not None
        if unique_id != entry.unique_id:
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

        stop_id = data_updates.get(CONF_STOP_LOCATION_ID)
        if stop_id and stop_id != entry.data.get(CONF_STOP_LOCATION_ID):
            client = TranslinkClient(session=async_get_clientsession(self.hass))
            await client.fetch_stop_timetable(stop_id)

        region_only = CONF_REALTIME_REGION in data_updates and all(
            value == entry.data.get(key)
            for key, value in data_updates.items()
            if key != CONF_REALTIME_REGION
        )
        options = (
            entry.options
            if region_only
            else {
                key: value
                for key, value in entry.options.items()
                if key not in _RECONFIGURED_OPTIONS
            }
        )
        if options != entry.options:
            return self.async_update_reload_and_abort(
                entry, unique_id=unique_id, data_updates=data_updates, options=options
            )
        return self.async_update_reload_and_abort(
            entry, unique_id=unique_id, data_updates=data_updates
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry."""
        self._reconfigure_entry = self._get_reconfigure_entry()
        if self._reconfigure_entry is None:
            return self.async_abort(reason="reconfigure_failed")
        current_data = self._reconfigure_entry.data
        if current_data.get(CONF_MODE) == MODE_NOTICES:
            return await self.async_step_notices_reconfigure(user_input)

        if current_data.get(CONF_MODE) == MODE_WINDOW:
            return await self.async_step_window_reconfigure(user_input)

        mode = (
            MODE_JOURNEY
            if current_data.get(CONF_MODE, MODE_JOURNEY) == MODE_JOURNEY
            else MODE_STOP
        )

        errors: dict[str, str] = {}
        if user_input is not None and (
            result := await self._async_search_locations(mode, user_input, errors)
        ):
            return result

        region_fields = {}
        if mode == MODE_JOURNEY:
            region, _ = resolve_realtime_region(current_data)
            region_fields[vol.Required(CONF_REALTIME_REGION, default=region)] = (
                _realtime_region_selector()
            )
        schema = vol.Schema(
            {
                **{
                    vol.Required(
                        name_field, default=current_data.get(name_field, "")
                    ): selector.TextSelector()
                    for _, name_field, _ in _LOCATION_FIELDS[mode]
                },
                **region_fields,
                vol.Required(
                    CONF_TRANSPORT_MODES,
                    default=current_data.get(
                        CONF_TRANSPORT_MODES, DEFAULT_TRANSPORT_MODES
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=AVAILABLE_TRANSPORT_MODES,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )


class TranslinkOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Translink options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage Translink options."""
        entry = self.config_entry
        if entry.data.get(CONF_MODE) == MODE_WINDOW:
            return await self.async_step_window_options(user_input)
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_data = {**entry.data, **entry.options}

        scan_interval = {
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=current_data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=600,
                    step=10,
                    unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }

        if entry.data.get(CONF_MODE) == MODE_NOTICES:
            return self.async_show_form(
                step_id="notices", data_schema=vol.Schema(scan_interval)
            )

        schema = vol.Schema(
            {
                **scan_interval,
                vol.Required(
                    CONF_TIME_SEARCH_MODE,
                    default=current_data.get(
                        CONF_TIME_SEARCH_MODE, DEFAULT_TIME_SEARCH_MODE
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=AVAILABLE_TIME_SEARCH_MODES,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_WALKING_SPEED,
                    default=current_data.get(CONF_WALKING_SPEED, DEFAULT_WALKING_SPEED),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=AVAILABLE_WALKING_SPEEDS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_MAX_WALKING_DISTANCE,
                    default=current_data.get(
                        CONF_MAX_WALKING_DISTANCE, DEFAULT_MAX_WALKING_DISTANCE
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=500,
                        max=10000,
                        step=250,
                        unit_of_measurement="m",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_FARE_PREFERENCE,
                    default=current_data.get(
                        CONF_FARE_PREFERENCE, DEFAULT_FARE_PREFERENCE
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=AVAILABLE_FARE_PREFERENCES,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_TRACK_VEHICLE,
                    default=current_data.get(CONF_TRACK_VEHICLE, DEFAULT_TRACK_VEHICLE),
                ): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_notices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the scan interval for a notice entry."""
        return await self.async_step_init(user_input)

    async def async_step_window_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit polling and alert settings for the window."""
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            errors = {
                key: "window_whole_number_required"
                for key, value in user_input.items()
                if not float(value).is_integer()
            }
            if not errors:
                return self.async_create_entry(
                    title="",
                    data={key: int(value) for key, value in user_input.items()},
                )
            current.update(user_input)

        return self.async_show_form(
            step_id="window_options",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        key, default=current.get(key, default)
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=minimum,
                            max=maximum,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    )
                    for key, (default, minimum, maximum) in WINDOW_OPTION_LIMITS.items()
                }
            ),
            errors=errors,
        )
