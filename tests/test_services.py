"""Home Assistant action tests with synthetic Translink planner responses."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, SupportsResponse
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
    UnknownUser,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service import async_get_all_descriptions
from pytest_homeassistant.common import MockConfigEntry

from custom_components.translink import async_setup
from custom_components.translink.api.models import JourneySummary
from custom_components.translink.const import DOMAIN, JP_API_BASE_URL
from custom_components.translink.coordinator import TranslinkCoordinator

if TYPE_CHECKING:
    from homeassistant.auth.models import User
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker


PLAN_URL = re.compile(rf"^{re.escape(JP_API_BASE_URL)}/api/plan\?id=-?\d+$")


@pytest.fixture
async def planner_action(hass: HomeAssistant) -> None:
    """Expose the action through Home Assistant's service registry."""
    with patch.object(hass, "http", create=True) as mock_http:
        mock_http.async_register_static_paths = AsyncMock()
        assert await async_setup(hass, {})


def register_itinerary(hass: HomeAssistant, entry: MockConfigEntry | None) -> str:
    """Create a registry itinerary associated with the supplied entry."""
    return (
        er.async_get(hass)
        .async_get_or_create(
            "sensor", DOMAIN, "trip", config_entry=entry, translation_key="itinerary"
        )
        .entity_id
    )


@pytest.fixture
async def journey_entity(hass: HomeAssistant) -> str:
    """Create a loaded journey with data and options at their normal locations."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        state=ConfigEntryState.LOADED,
        data={
            "mode": "journey",
            "start_location_id": "ST:place_censta",
            "start_name": "Central",
            "end_location_id": "ST:place_spcsta",
            "end_name": "Springfield Central",
            "max_walking_distance": 4000,
        },
        options={
            "transport_modes": ["Train"],
            "max_walking_distance": 1000,
            "walking_speed": "Slow",
        },
    )
    entry.add_to_hass(hass)
    coordinator = TranslinkCoordinator(hass, entry)
    coordinator.data = JourneySummary(status="scheduled")
    entry.runtime_data = coordinator
    return register_itinerary(hass, entry)


async def call_planner(
    hass: HomeAssistant,
    entity_id: str,
    *,
    context: Context | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Call the registered action and request the planner response."""
    response = await hass.services.async_call(
        DOMAIN,
        "plan_journey",
        {"entity_id": entity_id, "date": "2026-10-06", "time": "00:00", **fields},
        blocking=True,
        context=context,
        return_response=True,
    )
    assert response is not None
    return response


@pytest.mark.usefixtures("planner_action")
async def test_planner_action_registered_without_entries(hass: HomeAssistant) -> None:
    """The integration exposes a response-only action at global setup."""
    assert (
        hass.services.supports_response(DOMAIN, "plan_journey") is SupportsResponse.ONLY
    )
    descriptions = await async_get_all_descriptions(hass)
    fields = descriptions[DOMAIN]["plan_journey"]["fields"]
    assert fields["entity_id"]["selector"]["entity"]["filter"] == [
        {"integration": DOMAIN, "domain": ["sensor"]}
    ]
    assert fields["time"]["required"] is True
    assert fields["limit"]["default"] == 5


@pytest.mark.usefixtures("planner_action")
async def test_planner_action_uses_loaded_settings_for_one_explicit_request(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    journey_entity: str,
    plan_response_data: dict[str, Any],
) -> None:
    """A manual request reuses options and leaves the current journey data alone."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    coordinator = entry.runtime_data
    before = coordinator.data
    aioclient_mock.post(PLAN_URL, json=plan_response_data)

    result = await call_planner(hass, journey_entity, time_search_mode="ArriveBefore")

    assert result["sort_by"] == "departure"
    assert result["returned"] == 2
    assert [item["planner_index"] for item in result["alternatives"]] == [1, 0]
    assert result["alternatives"][1]["planner_first"] is True
    assert coordinator.data is before
    [(method, _, data, _)] = aioclient_mock.mock_calls
    assert method == "POST"
    form = parse_qs(data)
    assert form["searchDate"] == ["2026-10-06"]
    assert form["searchTime"] == ["12:00am"]
    assert form["timeSearchMode"] == ["ArriveBefore"]
    assert form["startLocationId"] == ["ST:place_censta"]
    assert form["start"] == ["Central"]
    assert form["endLocationId"] == ["ST:place_spcsta"]
    assert form["end"] == ["Springfield Central"]
    assert form["transportModes"] == ["Train"]
    assert form["maximumWalkingDistance"] == ["1000"]
    assert form["walkingSpeed"] == ["Slow"]


@pytest.mark.usefixtures("planner_action")
async def test_planner_action_returns_empty_response(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    journey_entity: str,
    plan_response_empty: dict[str, Any],
) -> None:
    """An empty itinerary list is a successful action response."""
    aioclient_mock.post(PLAN_URL, json=plan_response_empty)
    assert await call_planner(hass, journey_entity) == {
        "sort_by": "departure",
        "total_alternatives": 0,
        "returned": 0,
        "truncated": False,
        "alternatives": [],
        "plan_notices": [],
    }


@pytest.mark.usefixtures("planner_action")
@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"date": "not-a-date"}, "date"),
        ({"time": "25:00"}, "time"),
        ({"time_search_mode": "Now"}, "time_search_mode"),
        ({"sort_by": "fare"}, "sort_by"),
        ({"limit": 0}, "limit"),
        ({"limit": 11}, "limit"),
        ({"limit": 2.5}, "limit"),
    ],
)
async def test_planner_action_rejects_invalid_inputs(
    hass: HomeAssistant, fields: dict[str, Any], message: str
) -> None:
    """The action validates user input before resolving a sensor."""
    with pytest.raises((vol.Invalid, ServiceValidationError), match=message):
        await call_planner(hass, "sensor.missing", **fields)


@pytest.mark.usefixtures("planner_action")
@pytest.mark.parametrize(
    ("case", "key"),
    [
        ("missing", "planner_entity"),
        ("other_platform", "planner_entity"),
        ("other_sensor", "planner_itinerary"),
        ("other_entity_domain", "planner_itinerary"),
        ("no_entry", "planner_entry"),
        ("other_entry_domain", "planner_entry"),
        ("unloaded", "planner_unloaded"),
        ("missing_coordinator", "planner_unloaded"),
        ("stop_mode", "planner_journey_mode"),
    ],
)
async def test_planner_action_requires_loaded_journey_itinerary(
    hass: HomeAssistant, case: str, key: str
) -> None:
    """The service rejects unusable sensor and config-entry associations."""
    entry = None
    if case != "no_entry":
        entry = MockConfigEntry(
            domain="other" if case == "other_entry_domain" else DOMAIN,
            state=(
                ConfigEntryState.NOT_LOADED
                if case == "unloaded"
                else ConfigEntryState.LOADED
            ),
            data={"mode": "stop" if case == "stop_mode" else "journey"},
        )
        entry.add_to_hass(hass)
        if case == "stop_mode":
            entry.runtime_data = TranslinkCoordinator(hass, entry)

    entity_id = "sensor.missing"
    if case != "missing":
        entity_id = (
            er.async_get(hass)
            .async_get_or_create(
                "binary_sensor" if case == "other_entity_domain" else "sensor",
                "other" if case == "other_platform" else DOMAIN,
                "trip",
                config_entry=entry,
                translation_key="duration" if case == "other_sensor" else "itinerary",
            )
            .entity_id
        )

    with pytest.raises(ServiceValidationError) as raised:
        await call_planner(hass, entity_id)
    assert raised.value.translation_key == key


@pytest.mark.usefixtures("planner_action")
async def test_planner_action_wraps_upstream_failure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, journey_entity: str
) -> None:
    """An upstream planner failure has a translatable Home Assistant error."""
    aioclient_mock.post(PLAN_URL, status=503)

    with pytest.raises(HomeAssistantError) as raised:
        await call_planner(hass, journey_entity)
    assert raised.value.translation_key == "planner_upstream"


@pytest.mark.usefixtures("planner_action")
async def test_planner_action_propagates_cancellation(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, journey_entity: str
) -> None:
    """Cancelled requests do not report an upstream service error."""
    aioclient_mock.post(PLAN_URL, exc=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await call_planner(hass, journey_entity)


@pytest.mark.usefixtures("planner_action")
@pytest.mark.parametrize("authorization", ["read", "denied", "unknown"])
async def test_planner_action_checks_itinerary_read_permission(
    hass: HomeAssistant,
    hass_read_only_user: User,
    aioclient_mock: AiohttpClientMocker,
    journey_entity: str,
    plan_response_empty: dict[str, Any],
    authorization: str,
) -> None:
    """Only a user who can read this itinerary can request its alternatives."""
    context = Context(
        user_id=hass_read_only_user.id if authorization != "unknown" else "unknown"
    )
    aioclient_mock.post(PLAN_URL, json=plan_response_empty)
    if authorization == "read":
        assert (await call_planner(hass, journey_entity, context=context))[
            "returned"
        ] == 0
        assert len(aioclient_mock.mock_calls) == 1
    else:
        with (
            patch.object(
                type(hass_read_only_user.permissions),
                "check_entity",
                return_value=False,
            ) as check,
            pytest.raises(UnknownUser if authorization == "unknown" else Unauthorized),
        ):
            await call_planner(hass, journey_entity, context=context)
        if authorization == "denied":
            check.assert_called_once_with(journey_entity, "read")
        assert not aioclient_mock.mock_calls
