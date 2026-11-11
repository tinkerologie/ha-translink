"""Config flow for Translink Queensland integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.client import plan_matches_realtime_region
from .client import LocationSearchResult, TranslinkApiError, TranslinkClient
from .const import (
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
    MODE_STOP,
    REALTIME_FEED_REGIONS,
    REALTIME_REGION_NONE,
    resolve_realtime_region,
)

_LOGGER = logging.getLogger(__name__)

_LOCATION_FIELDS = {
    MODE_JOURNEY: (
        (CONF_START_LOCATION_ID, CONF_START_NAME, "start_query"),
        (CONF_END_LOCATION_ID, CONF_END_NAME, "end_query"),
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
_LOCATION_LABELS = {
    "station": "Station",
    "place": "Place or address",
    "unknown": "Location",
}


def _realtime_region_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[*REALTIME_FEED_REGIONS, REALTIME_REGION_NONE],
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key=CONF_REALTIME_REGION,
        )
    )


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
                                value=MODE_STOP,
                                label="Stop / Station (Departure Board)",
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

    async def async_step_stop_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a stop or station from the search matches."""
        return await self._async_step_location_selection(MODE_STOP, user_input)

    async def _async_step_location_selection(
        self, mode: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Validate the submitted locations and commit the confirmed results."""
        errors: dict[str, str] = {}
        if user_input is not None and (
            result := await self._async_confirm_locations(mode, user_input, errors)
        ):
            return result
        if errors.get("base") == "region_mismatch":
            return self._show_journey_form(errors, self._pending_input)
        return self._show_location_selection(mode, errors)

    def _show_location_selection(
        self, mode: str, errors: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Show selectors only for fields with several matches."""
        saved_data = self._reconfigure_entry.data if self._reconfigure_entry else {}
        fields = dict(
            _location_selector(id_field, candidates, saved_data.get(id_field))
            for id_field, candidates in self._candidates.items()
            if len(candidates) > 1
        )
        return self.async_show_form(
            step_id=f"{mode}_select",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders=self._queries,
        )

    async def _async_confirm_locations(
        self,
        mode: str,
        selection: dict[str, Any],
        errors: dict[str, str],
    ) -> ConfigFlowResult | None:
        """Resolve single matches and confirm selections before saving locations."""
        locations: dict[str, LocationSearchResult] = {}
        for id_field, candidates in self._candidates.items():
            if len(candidates) == 1:
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

        try:
            if self.source == config_entries.SOURCE_RECONFIGURE:
                return await self._async_finish_reconfigure(unique_id, data)
            return await self._async_finish_setup(mode, unique_id, data, errors)
        except AbortFlow:
            raise
        except TranslinkApiError:
            errors["base"] = "cannot_connect"
        except Exception:
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

        default_name = "Translink Journey" if mode == MODE_JOURNEY else "Translink Stop"
        name = str(self._pending_input.get(CONF_NAME, "")).strip() or default_name
        data.update(
            {
                CONF_MODE: mode,
                CONF_NAME: name,
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            }
        )
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
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        entry = self.config_entry
        current_data = {**entry.data, **entry.options}

        schema = vol.Schema(
            {
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
