"""On-demand Translink journey planning for Home Assistant actions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.client import (
    TranslinkApiError,
    TranslinkClient,
    build_journey_alternatives,
)
from .const import (
    AVAILABLE_TIME_SEARCH_MODES,
    BRISBANE_TZ,
    CONF_TIME_SEARCH_MODE,
    DEFAULT_ALTERNATIVES_LIMIT,
    DEFAULT_TIME_SEARCH_MODE,
    DOMAIN,
    JOURNEY_SORT_OPTIONS,
    MAX_ALTERNATIVES_LIMIT,
    MODE_JOURNEY,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import TranslinkCoordinator

SERVICE_PLAN_JOURNEY = "plan_journey"

PLAN_JOURNEY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required("date"): cv.date,
        vol.Required("time"): cv.time,
        vol.Optional(CONF_TIME_SEARCH_MODE, default=DEFAULT_TIME_SEARCH_MODE): vol.In(
            AVAILABLE_TIME_SEARCH_MODES
        ),
        vol.Optional("sort_by", default="departure"): vol.In(JOURNEY_SORT_OPTIONS),
        vol.Optional("limit", default=DEFAULT_ALTERNATIVES_LIMIT): vol.All(
            int, vol.Range(min=1, max=MAX_ALTERNATIVES_LIMIT)
        ),
    }
)


def _journey_coordinator(hass: HomeAssistant, entity_id: str) -> TranslinkCoordinator:
    """Resolve a registered itinerary sensor to its loaded journey."""
    entity = er.async_get(hass).async_get(entity_id)
    if entity is None or entity.platform != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="planner_entity"
        )
    if entity.domain != "sensor" or entity.translation_key != "itinerary":
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="planner_itinerary"
        )
    entry = (
        hass.config_entries.async_get_entry(entity.config_entry_id)
        if entity.config_entry_id is not None
        else None
    )
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="planner_entry"
        )
    coordinator: TranslinkCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if entry.state is not ConfigEntryState.LOADED or coordinator is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="planner_unloaded"
        )
    if coordinator.mode != MODE_JOURNEY:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="planner_journey_mode"
        )
    return coordinator


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the action independently of any config entry."""

    async def async_plan_journey(call: ServiceCall) -> ServiceResponse:
        coordinator = _journey_coordinator(hass, call.data[ATTR_ENTITY_ID])
        target = datetime.combine(
            call.data["date"], call.data["time"], ZoneInfo(BRISBANE_TZ)
        )
        client = TranslinkClient(session=async_get_clientsession(hass))
        try:
            plan = await client.plan_journey(
                start_location_id=coordinator.start_location_id,
                start_name=coordinator.start_name,
                end_location_id=coordinator.end_location_id,
                end_name=coordinator.end_name,
                transport_modes=coordinator.transport_modes,
                time_search_mode=call.data[CONF_TIME_SEARCH_MODE],
                max_walking_distance=coordinator.max_walking_distance,
                walking_speed=coordinator.walking_speed,
                target_datetime=target,
            )
        except TranslinkApiError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="planner_upstream"
            ) from err
        # The bounded payload uses only JSON-safe fields.
        return cast(
            "ServiceResponse",
            build_journey_alternatives(plan, call.data["sort_by"], call.data["limit"]),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_PLAN_JOURNEY,
        async_plan_journey,
        schema=PLAN_JOURNEY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
