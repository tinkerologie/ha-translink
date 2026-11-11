"""Tests for Translink config flow and options flow."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import AbortFlow, FlowResultType, InvalidData
from pytest_homeassistant.common import MockConfigEntry

from custom_components.translink.api.models import NearbyStop
from custom_components.translink.client import (
    JourneyPlanResult,
    LocationSearchResult,
    TranslinkApiError,
    TranslinkConnectionError,
    TranslinkResponseError,
)
from custom_components.translink.config_flow import TranslinkConfigFlow
from custom_components.translink.const import (
    CONF_END_LOCATION_ID,
    CONF_END_NAME,
    CONF_MODE,
    CONF_NAME,
    CONF_REALTIME_REGION,
    CONF_SCAN_INTERVAL,
    CONF_START_LOCATION_ID,
    CONF_START_NAME,
    CONF_STOP_LOCATION_ID,
    CONF_STOP_NAME,
    CONF_TRACK_VEHICLE,
    CONF_TRANSPORT_MODES,
    DOMAIN,
    MODE_JOURNEY,
    MODE_STOP,
)


async def test_step_user_show_form(hass: HomeAssistant) -> None:
    """Test user step displays mode selection."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_step_user_select_journey(hass: HomeAssistant) -> None:
    """Test user step navigates to journey."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MODE: MODE_JOURNEY},
    )
    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "journey"


async def test_step_user_select_stop(hass: HomeAssistant) -> None:
    """Test user step navigates to stop."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MODE: MODE_STOP},
    )
    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "stop"


async def _start_nearby_flow(hass: HomeAssistant, source: str) -> ConfigFlowResult:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    flow_id = result["flow_id"]
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_MODE: "nearby_stop"}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "nearby"
    assert result["menu_options"] == ["nearby_zone", "nearby_point"]
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"next_step_id": source}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == source
    return result


async def test_nearby_point_requires_confirmation_even_for_one_stop(
    hass: HomeAssistant,
) -> None:
    """Ask the user to confirm the exact platform ID before validating its board."""
    result = await _start_nearby_flow(hass, "nearby_point")
    flow_id = result["flow_id"]
    assert result["data_schema"].schema["location"].config == {}
    lat, lng = -26.345678, 152.456789
    stop_id = "SI:000014"
    with (
        patch(
            "custom_components.translink.client.TranslinkClient.find_nearby_stops",
            return_value=[
                NearbyStop(id=stop_id, description="Public platform", distanceM=31)
            ],
        ) as lookup,
        patch(
            "custom_components.translink.client.TranslinkClient.fetch_stop_timetable",
        ) as timetable,
        patch("custom_components.translink.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id, {"location": {ATTR_LATITUDE: lat, ATTR_LONGITUDE: lng}}
        )
        lookup.assert_awaited_once_with(lat, lng)
        timetable.assert_not_awaited()
        assert result["step_id"] == "nearby_select"
        assert result["data_schema"].schema[CONF_STOP_LOCATION_ID].config[
            "options"
        ] == [{"value": stop_id, "label": "Public platform · SI:000014 · 31 m"}]
        with pytest.raises(InvalidData):
            await hass.config_entries.flow.async_configure(
                flow_id, {CONF_STOP_LOCATION_ID: "SI:000138"}
            )
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_STOP_LOCATION_ID: stop_id, CONF_NAME: "Public board"}
        )

    timetable.assert_awaited_once_with(stop_id)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_MODE: MODE_STOP,
        CONF_NAME: "Public board",
        CONF_STOP_LOCATION_ID: stop_id,
        CONF_STOP_NAME: "Public platform",
        CONF_TRANSPORT_MODES: ["Bus", "Ferry", "Train", "Tram"],
        CONF_SCAN_INTERVAL: 60,
    }
    assert result["result"].unique_id == "stop_SI:000014"
    assert result["result"].options == {}


async def test_nearby_zone_groups_platforms_and_preserves_the_exact_id(
    hass: HomeAssistant,
) -> None:
    """Offer platform IDs in station groups, ordered by each group's closest stop."""
    result = await _start_nearby_flow(hass, "nearby_zone")
    flow_id = result["flow_id"]
    assert result["data_schema"].schema["zone"].config["domain"] == ["zone"]
    zone_id = "zone.synthetic_away"
    lat, lng = -26.345678, 152.456789
    hass.states.async_set(zone_id, "0", {ATTR_LATITUDE: lat, ATTR_LONGITUDE: lng})
    rows = [
        NearbyStop.model_validate(row)
        for row in [
            {
                "id": "SI:010783",
                "description": "Platform 3",
                "distanceM": 42,
                "station": {"id": "ST:place_kgbs", "name": "King George Square"},
            },
            {"id": "SI:900001", "description": "Street stop", "distanceM": 31},
            {
                "id": "SI:000138",
                "description": "Platform 2",
                "distanceM": 31,
                "station": {"id": "ST:place_kgbs", "name": "King George Square"},
            },
            {
                "id": "SI:000014",
                "description": "Platform 1",
                "distanceM": 31,
                "station": {"id": "ST:place_kgbs", "name": "King George Square"},
            },
            {
                "id": "ST:place_kgbs",
                "description": "King George Square",
                "distanceM": 1,
            },
        ]
    ]
    with (
        patch(
            "custom_components.translink.client.TranslinkClient.find_nearby_stops",
            return_value=rows,
        ) as lookup,
        patch(
            "custom_components.translink.client.TranslinkClient.fetch_stop_timetable",
        ) as timetable,
        patch("custom_components.translink.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id, {"zone": zone_id}
        )
        lookup.assert_awaited_once_with(lat, lng)
        assert result["description_placeholders"] == {}
        assert result["data_schema"].schema[CONF_STOP_LOCATION_ID].config[
            "options"
        ] == [
            {
                "value": "SI:000014",
                "label": "King George Square — Platform 1 · SI:000014 · 31 m",
            },
            {
                "value": "SI:000138",
                "label": "King George Square — Platform 2 · SI:000138 · 31 m",
            },
            {
                "value": "SI:010783",
                "label": "King George Square — Platform 3 · SI:010783 · 42 m",
            },
            {"value": "SI:900001", "label": "Street stop · SI:900001 · 31 m"},
        ]
        flow = hass.config_entries.flow._progress[flow_id]
        for private_value in (str(lat), str(lng), zone_id):
            assert private_value not in repr(vars(flow))
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {CONF_STOP_LOCATION_ID: "SI:010783", CONF_TRANSPORT_MODES: ["Bus"]},
        )

    timetable.assert_awaited_once_with("SI:010783")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_MODE: MODE_STOP,
        CONF_NAME: "Station Board",
        CONF_STOP_LOCATION_ID: "SI:010783",
        CONF_STOP_NAME: "Platform 3",
        CONF_TRANSPORT_MODES: ["Bus"],
        CONF_SCAN_INTERVAL: 60,
    }
    assert result["result"].unique_id == "stop_SI:010783"
    assert result["result"].options == {}
    assert "SI:000014" not in repr(vars(flow))


@pytest.mark.parametrize(
    "point",
    [
        None,
        {ATTR_LATITUDE: 10},
        {ATTR_LATITUDE: True, ATTR_LONGITUDE: 20},
        {ATTR_LATITUDE: "-30", ATTR_LONGITUDE: 20},
        {ATTR_LATITUDE: float("nan"), ATTR_LONGITUDE: 20},
        {ATTR_LATITUDE: 10, ATTR_LONGITUDE: 181},
    ],
)
async def test_nearby_point_reports_an_invalid_location(
    hass: HomeAssistant, point
) -> None:
    """Show the location-specific error without submitting an invalid map point."""
    result = await _start_nearby_flow(hass, "nearby_point")
    with patch(
        "custom_components.translink.client.TranslinkClient.find_nearby_stops",
    ) as lookup:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"location": point}
        )
    lookup.assert_not_awaited()
    assert result["step_id"] == "nearby_point"
    assert result["errors"] == {"location": "location_unavailable"}


@pytest.mark.parametrize(
    "attributes",
    [
        None,
        {},
        {ATTR_LATITUDE: 10},
        {
            ATTR_LATITUDE: 10,
            ATTR_LONGITUDE: float("inf"),
        },
    ],
)
async def test_nearby_zone_reports_missing_location(
    hass: HomeAssistant, attributes
) -> None:
    """Handle missing zones and zone states without usable coordinates."""
    result = await _start_nearby_flow(hass, "nearby_zone")
    zone_id = "zone.synthetic_away"
    if attributes is not None:
        hass.states.async_set(zone_id, "0", attributes)
    with patch(
        "custom_components.translink.client.TranslinkClient.find_nearby_stops",
    ) as lookup:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"zone": zone_id}
        )
    lookup.assert_not_awaited()
    assert result["step_id"] == "nearby_zone"
    assert result["errors"] == {"zone": "location_unavailable"}


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (None, "no_nearby_stops"),
        (TranslinkConnectionError, "cannot_connect"),
        (RuntimeError, "unknown"),
        (AbortFlow, "already_configured"),
    ],
)
async def test_nearby_lookup_errors_do_not_expose_coordinates(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    failure: type[Exception] | None,
    expected: str,
) -> None:
    """Keep no-results and upstream failures distinct and location details out of logs."""
    result = await _start_nearby_flow(hass, "nearby_point")
    lat, lng = -26.345678, 152.456789
    side_effect = (
        AbortFlow(expected)
        if failure is AbortFlow
        else failure(f"{lat} {lng}")
        if failure
        else None
    )
    with patch(
        "custom_components.translink.client.TranslinkClient.find_nearby_stops",
        side_effect=side_effect,
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"location": {ATTR_LATITUDE: lat, ATTR_LONGITUDE: lng}}
        )
    if failure is AbortFlow:
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == expected
    else:
        assert result["step_id"] == "nearby_point"
        assert result["errors"] == {"base": expected}
    assert str(lat) not in caplog.text
    assert str(lng) not in caplog.text


async def test_nearby_stop_rejects_an_already_configured_board(
    hass: HomeAssistant,
) -> None:
    """Apply the existing stop ID uniqueness rule to a nearby match."""
    result = await _start_nearby_flow(hass, "nearby_point")
    flow_id = result["flow_id"]
    stop_id = "SI:000014"
    MockConfigEntry(domain=DOMAIN, unique_id=f"stop_{stop_id}").add_to_hass(hass)
    with (
        patch(
            "custom_components.translink.client.TranslinkClient.find_nearby_stops",
            return_value=[NearbyStop(id=stop_id, description="Platform", distanceM=31)],
        ),
        patch(
            "custom_components.translink.client.TranslinkClient.fetch_stop_timetable",
        ) as timetable,
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id, {"location": {ATTR_LATITUDE: 10, ATTR_LONGITUDE: 20}}
        )
        assert result["step_id"] == "nearby_select"
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_STOP_LOCATION_ID: stop_id}
        )
    timetable.assert_not_awaited()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_nearby_confirmation_error_preserves_the_picker_and_private_location(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Retain the candidates after a validation error and log only its type."""
    result = await _start_nearby_flow(hass, "nearby_point")
    flow_id = result["flow_id"]
    lat, lng = -26.345678, 152.456789
    stop_id = "SI:000014"
    with (
        patch(
            "custom_components.translink.client.TranslinkClient.find_nearby_stops",
            return_value=[NearbyStop(id=stop_id, description="Platform", distanceM=31)],
        ) as lookup,
        patch(
            "custom_components.translink.client.TranslinkClient.fetch_stop_timetable",
            side_effect=[RuntimeError(f"{lat} {lng}"), None],
        ) as timetable,
        patch("custom_components.translink.async_setup_entry", return_value=True),
    ):
        await hass.config_entries.flow.async_configure(
            flow_id, {"location": {ATTR_LATITUDE: lat, ATTR_LONGITUDE: lng}}
        )
        selection = {CONF_STOP_LOCATION_ID: stop_id}
        result = await hass.config_entries.flow.async_configure(flow_id, selection)
        assert result["step_id"] == "nearby_select"
        assert result["errors"] == {"base": "unknown"}
        assert str(lat) not in caplog.text
        assert str(lng) not in caplog.text
        result = await hass.config_entries.flow.async_configure(flow_id, selection)
    lookup.assert_awaited_once_with(lat, lng)
    assert timetable.await_args_list == [call(stop_id), call(stop_id)]
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_step_journey_success(hass: HomeAssistant) -> None:
    """Test successful journey configuration."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MODE: MODE_JOURNEY},
    )

    start_loc = LocationSearchResult(
        LocationId="ST:place_censta", Description="Central station"
    )
    end_loc = LocationSearchResult(
        LocationId="ST:place_spcsta", Description="Springfield Central"
    )

    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=[[start_loc], [end_loc]],
        ),
        patch(
            "custom_components.translink.client.TranslinkClient.plan_journey",
            return_value=JourneyPlanResult(),
        ),
        patch(
            "custom_components.translink.async_setup_entry",
            return_value=True,
        ),
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {
                CONF_NAME: "Work Commute",
                CONF_START_NAME: "Central station",
                CONF_END_NAME: "Springfield Central",
                CONF_TRANSPORT_MODES: ["Bus", "Train"],
            },
        )

    assert result3["type"] is FlowResultType.CREATE_ENTRY
    assert result3["title"] == "Work Commute"
    assert result3["data"][CONF_MODE] == MODE_JOURNEY
    assert result3["data"]["start_location_id"] == "ST:place_censta"
    assert result3["data"]["end_location_id"] == "ST:place_spcsta"


async def test_step_journey_location_not_found(hass: HomeAssistant) -> None:
    """Test location not found errors."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MODE: MODE_JOURNEY},
    )

    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            return_value=[],
        ),
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {
                CONF_NAME: "Work Commute",
                CONF_START_NAME: "Unknown Station",
                CONF_END_NAME: "Another Station",
            },
        )

    assert result3["type"] is FlowResultType.FORM
    assert result3["step_id"] == "journey"
    assert result3["errors"][CONF_START_NAME] == "location_not_found"
    assert result3["errors"][CONF_END_NAME] == "location_not_found"


async def test_step_journey_cannot_connect(hass: HomeAssistant) -> None:
    """Test network failure in journey step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MODE: MODE_JOURNEY},
    )

    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=TranslinkConnectionError("Network error"),
        ),
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {
                CONF_NAME: "Work Commute",
                CONF_START_NAME: "Central",
                CONF_END_NAME: "Springfield",
            },
        )

    assert result3["type"] is FlowResultType.FORM
    assert result3["step_id"] == "journey"
    assert result3["errors"]["base"] == "cannot_connect"


async def test_step_stop_success(hass: HomeAssistant) -> None:
    """Test configuring a stop departure board."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MODE: MODE_STOP},
    )

    stop_loc = LocationSearchResult(
        LocationId="ST:place_romsta", Description="Roma Street station"
    )

    with (
        patch(
            "custom_components.translink.client.TranslinkClient.fetch_stop_timetable"
        ) as timetable,
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            return_value=[
                LocationSearchResult(
                    LocationId="PL:parkland", Description="Roma Street Parkland"
                ),
                stop_loc,
            ],
        ),
        patch(
            "custom_components.translink.async_setup_entry",
            return_value=True,
        ),
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {
                CONF_NAME: "Roma Street",
                CONF_STOP_NAME: "Roma Street",
                CONF_TRANSPORT_MODES: ["Train"],
            },
        )

    timetable.assert_awaited_once_with("ST:place_romsta")
    assert result3["type"] is FlowResultType.CREATE_ENTRY
    assert result3["title"] == "Roma Street"
    assert result3["data"][CONF_MODE] == MODE_STOP
    assert result3["data"]["stop_location_id"] == "ST:place_romsta"


_ROMA_STREET_RESULTS = [
    LocationSearchResult(LocationId="PL:parkland", Description="Roma Street Parkland"),
    LocationSearchResult(LocationId="PL:street", Description="Roma Street, Brisbane"),
    LocationSearchResult(
        LocationId="ST:place_rompl", Description="Roma Street busway station"
    ),
    LocationSearchResult(
        LocationId="ST:place_romsta", Description="Roma Street station"
    ),
    LocationSearchResult(LocationId="SI:600036", Description="Roma Street platform 4"),
]


async def test_stop_search_confirms_a_board_candidate(hass: HomeAssistant) -> None:
    """Offer only valid board candidates and keep the confirmed public ID."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    flow_id = result["flow_id"]
    await hass.config_entries.flow.async_configure(flow_id, {CONF_MODE: MODE_STOP})

    with (
        patch(
            "custom_components.translink.client.TranslinkClient.fetch_stop_timetable",
            side_effect=[TranslinkResponseError("Unavailable timetable"), None],
        ) as timetable,
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            return_value=[*_ROMA_STREET_RESULTS, _ROMA_STREET_RESULTS[-1]],
        ),
        patch("custom_components.translink.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_NAME: "Roma Street", CONF_STOP_NAME: "Roma Street"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "stop_select"
        assert result["description_placeholders"] == {"stop_query": "Roma Street"}
        assert result["data_schema"].schema[CONF_STOP_LOCATION_ID].config[
            "options"
        ] == [
            {
                "value": "ST:place_rompl",
                "label": "Roma Street busway station — Station",
            },
            {"value": "ST:place_romsta", "label": "Roma Street station — Station"},
            {"value": "SI:600036", "label": "Roma Street platform 4 — Stop 600036"},
        ]

        timetable.assert_not_awaited()
        with pytest.raises(InvalidData):
            await hass.config_entries.flow.async_configure(
                flow_id, {CONF_STOP_LOCATION_ID: "PL:parkland"}
            )
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_STOP_LOCATION_ID: "SI:600036"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "stop_select"
        assert result["errors"] == {"base": "cannot_connect"}
        timetable.assert_awaited_once_with("SI:600036")
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_STOP_LOCATION_ID: "SI:600036"}
        )

    assert timetable.await_args_list == [call("SI:600036"), call("SI:600036")]
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_STOP_LOCATION_ID] == "SI:600036"
    assert result["data"][CONF_STOP_NAME] == "Roma Street platform 4"
    assert result["result"].unique_id == "stop_SI:600036"


async def test_journey_search_confirms_both_endpoints(hass: HomeAssistant) -> None:
    """Offer places and addresses as journey endpoints and save the confirmed IDs."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    flow_id = result["flow_id"]
    await hass.config_entries.flow.async_configure(flow_id, {CONF_MODE: MODE_JOURNEY})

    destination_results = [
        LocationSearchResult(
            LocationId="ST:place_censta", Description="Central station"
        ),
        LocationSearchResult(LocationId="PL:address", Description="255 Ann Street"),
    ]
    with (
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=[_ROMA_STREET_RESULTS, destination_results],
        ),
        patch(
            "custom_components.translink.client.TranslinkClient.plan_journey",
            return_value=JourneyPlanResult(),
        ) as plan,
        patch("custom_components.translink.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {
                CONF_NAME: "Work Commute",
                CONF_START_NAME: "Roma Street",
                CONF_END_NAME: "Ann Street",
                CONF_TRANSPORT_MODES: ["Train"],
                CONF_TRACK_VEHICLE: False,
            },
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "journey_select"
        assert {key.schema for key in result["data_schema"].schema} == {
            CONF_START_LOCATION_ID,
            CONF_END_LOCATION_ID,
        }
        assert result["description_placeholders"] == {
            "start_query": "Roma Street",
            "end_query": "Ann Street",
        }
        plan.assert_not_awaited()

        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {
                CONF_START_LOCATION_ID: "PL:street",
                CONF_END_LOCATION_ID: "PL:address",
            },
        )

    plan.assert_awaited_once_with(
        start_location_id="PL:street",
        start_name="Roma Street, Brisbane",
        end_location_id="PL:address",
        end_name="255 Ann Street",
        transport_modes=["Train"],
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Work Commute"
    assert result["result"].unique_id == "journey_PL:street_PL:address"
    assert result["data"][CONF_START_LOCATION_ID] == "PL:street"
    assert result["data"][CONF_START_NAME] == "Roma Street, Brisbane"
    assert result["data"][CONF_END_LOCATION_ID] == "PL:address"
    assert result["data"][CONF_END_NAME] == "255 Ann Street"
    assert result["data"][CONF_TRACK_VEHICLE] is False


async def test_options_flow(hass: HomeAssistant) -> None:
    """Test Translink options flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_MODE: MODE_JOURNEY, CONF_SCAN_INTERVAL: 60},
        options={},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_SCAN_INTERVAL: 120},
    )
    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_SCAN_INTERVAL] == 120


async def test_step_reconfigure_journey(hass: HomeAssistant) -> None:
    """Test reconfiguring an existing journey entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="journey_ST:old_1_ST:old_2",
        data={
            CONF_MODE: MODE_JOURNEY,
            CONF_NAME: "My Journey",
            CONF_START_NAME: "Central",
            CONF_END_NAME: "Springfield",
        },
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    start_loc = LocationSearchResult(
        LocationId="ST:place_censta", Description="Central station"
    )
    end_loc = LocationSearchResult(
        LocationId="ST:place_spcsta", Description="Springfield Central"
    )

    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=[[start_loc], [end_loc]],
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_START_NAME: "Central station",
                CONF_END_NAME: "Springfield Central",
            },
        )

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "reconfigure_successful"
    assert entry.data["start_location_id"] == "ST:place_censta"
    assert entry.data["end_location_id"] == "ST:place_spcsta"


async def test_step_reconfigure_stop(hass: HomeAssistant) -> None:
    """Test reconfiguring an existing stop entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="stop_ST:old_stop",
        data={
            CONF_MODE: MODE_STOP,
            CONF_NAME: "My Stop",
            CONF_STOP_NAME: "Roma Street",
        },
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    stop_loc = LocationSearchResult(
        LocationId="ST:place_romsta", Description="Roma Street station"
    )

    with (
        patch(
            "custom_components.translink.client.TranslinkClient.fetch_stop_timetable"
        ) as timetable,
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            return_value=[stop_loc],
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_STOP_NAME: "Roma Street station",
            },
        )

    timetable.assert_awaited_once_with("ST:place_romsta")
    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "reconfigure_successful"
    assert entry.data["stop_location_id"] == "ST:place_romsta"


async def test_step_journey_unknown_error(hass: HomeAssistant) -> None:
    """Test unexpected exception in journey config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MODE: MODE_JOURNEY},
    )

    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=RuntimeError("Unexpected bug"),
        ),
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {
                CONF_NAME: "Work Commute",
                CONF_START_NAME: "Central",
                CONF_END_NAME: "Springfield",
            },
        )

    assert result3["type"] is FlowResultType.FORM
    assert result3["step_id"] == "journey"
    assert result3["errors"]["base"] == "unknown"


async def test_step_stop_location_not_found(hass: HomeAssistant) -> None:
    """Test stop not found error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MODE: MODE_STOP},
    )

    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            return_value=[],
        ),
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {
                CONF_NAME: "My Station",
                CONF_STOP_NAME: "Unknown Place",
            },
        )

    assert result3["type"] is FlowResultType.FORM
    assert result3["step_id"] == "stop"
    assert result3["errors"][CONF_STOP_NAME] == "location_not_found"


async def test_step_stop_unknown_error(hass: HomeAssistant) -> None:
    """Test unexpected exception in stop config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MODE: MODE_STOP},
    )

    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=RuntimeError("Unexpected"),
        ),
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {
                CONF_NAME: "My Station",
                CONF_STOP_NAME: "Roma Street",
            },
        )

    assert result3["type"] is FlowResultType.FORM
    assert result3["step_id"] == "stop"
    assert result3["errors"]["base"] == "unknown"


async def test_step_reconfigure_journey_cannot_connect(hass: HomeAssistant) -> None:
    """Test connection error in journey reconfigure."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="journey_reconfig_err",
        data={
            CONF_MODE: MODE_JOURNEY,
            CONF_NAME: "My Journey",
            CONF_START_NAME: "Central",
            CONF_END_NAME: "Springfield",
        },
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=TranslinkConnectionError("Network timeout"),
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_START_NAME: "Central",
                CONF_END_NAME: "Springfield",
            },
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "reconfigure"
    assert result2["errors"]["base"] == "cannot_connect"


async def test_step_reconfigure_stop_cannot_connect(hass: HomeAssistant) -> None:
    """Test connection error in stop reconfigure."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="stop_reconfig_err",
        data={
            CONF_MODE: MODE_STOP,
            CONF_NAME: "My Stop",
            CONF_STOP_NAME: "Roma Street",
        },
    )
    entry.add_to_hass(hass)
    original = (entry.data, entry.options, entry.unique_id)

    result = await entry.start_reconfigure_flow(hass)
    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=TranslinkConnectionError("Network timeout"),
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_STOP_NAME: "Roma Street",
            },
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "reconfigure"
    assert result2["errors"]["base"] == "cannot_connect"

    assert (entry.data, entry.options, entry.unique_id) == original


async def test_step_stop_api_error(hass: HomeAssistant) -> None:
    """Test TranslinkApiError in stop step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MODE: MODE_STOP},
    )
    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=TranslinkApiError("API error"),
        ),
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {CONF_NAME: "Stop", CONF_STOP_NAME: "Station"},
        )
    assert result3["type"] is FlowResultType.FORM
    assert result3["step_id"] == "stop"
    assert result3["errors"]["base"] == "cannot_connect"


async def test_step_reconfigure_no_entry_aborts(hass: HomeAssistant) -> None:
    """Test reconfigure aborts cleanly if no reconfigure entry is found."""
    flow = TranslinkConfigFlow()
    flow.hass = hass
    flow._get_reconfigure_entry = MagicMock(return_value=None)  # type: ignore[method-assign]
    result = await flow.async_step_reconfigure()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_failed"


async def test_step_reconfigure_journey_location_not_found(
    hass: HomeAssistant,
) -> None:
    """Test reconfigure journey sets error when locations not found."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="journey_reconfig_not_found",
        data={
            CONF_MODE: MODE_JOURNEY,
            CONF_NAME: "My Journey",
            CONF_START_NAME: "Central",
            CONF_END_NAME: "Springfield",
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=[[], []],
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_START_NAME: "Bad Start", CONF_END_NAME: "Bad End"},
        )
    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "reconfigure"
    assert result2["errors"][CONF_START_NAME] == "location_not_found"
    assert result2["errors"][CONF_END_NAME] == "location_not_found"


async def test_step_reconfigure_stop_location_not_found(
    hass: HomeAssistant,
) -> None:
    """Test reconfigure stop sets error when stop not found."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="stop_reconfig_not_found",
        data={
            CONF_MODE: MODE_STOP,
            CONF_NAME: "My Stop",
            CONF_STOP_NAME: "Roma Street",
        },
    )
    entry.add_to_hass(hass)
    original = (entry.data, entry.options, entry.unique_id)
    result = await entry.start_reconfigure_flow(hass)
    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            return_value=[],
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_STOP_NAME: "Bad Stop"},
        )
    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "reconfigure"
    assert result2["errors"][CONF_STOP_NAME] == "location_not_found"

    assert (entry.data, entry.options, entry.unique_id) == original


async def test_step_reconfigure_journey_unexpected_error(
    hass: HomeAssistant,
) -> None:
    """Test unexpected exception in journey reconfigure."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="journey_reconfig_unexpected",
        data={
            CONF_MODE: MODE_JOURNEY,
            CONF_NAME: "My Journey",
            CONF_START_NAME: "Central",
            CONF_END_NAME: "Springfield",
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=RuntimeError("Crash"),
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_START_NAME: "Central", CONF_END_NAME: "Springfield"},
        )
    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "reconfigure"
    assert result2["errors"]["base"] == "unknown"


async def test_step_reconfigure_stop_unexpected_error(
    hass: HomeAssistant,
) -> None:
    """Test unexpected exception in stop reconfigure."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="stop_reconfig_unexpected",
        data={
            CONF_MODE: MODE_STOP,
            CONF_NAME: "My Stop",
            CONF_STOP_NAME: "Roma Street",
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=RuntimeError("Crash"),
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_STOP_NAME: "Roma Street"},
        )
    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "reconfigure"
    assert result2["errors"]["base"] == "unknown"


async def test_journey_already_configured(hass: HomeAssistant) -> None:
    """Reject a duplicate from the confirmed IDs before calling the planner."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="journey_ST:place_romsta_ST:place_spcsta",
        data={CONF_MODE: MODE_JOURNEY},
    )
    entry.add_to_hass(hass)

    end_loc = LocationSearchResult(
        LocationId="ST:place_spcsta", Description="Springfield Central"
    )
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow_id = flow["flow_id"]
    await hass.config_entries.flow.async_configure(flow_id, {CONF_MODE: MODE_JOURNEY})

    with (
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=[_ROMA_STREET_RESULTS, [end_loc]],
        ),
        patch(
            "custom_components.translink.client.TranslinkClient.plan_journey"
        ) as plan,
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {
                CONF_NAME: "Duplicate Commute",
                CONF_START_NAME: "Roma Street",
                CONF_END_NAME: "Springfield Central",
            },
        )
        assert result["step_id"] == "journey_select"
        assert [key.schema for key in result["data_schema"].schema] == [
            CONF_START_LOCATION_ID,
        ]
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_START_LOCATION_ID: "ST:place_romsta"}
        )

    plan.assert_not_awaited()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_stop_already_configured(hass: HomeAssistant) -> None:
    """Test stop setup aborts when unique_id is already configured."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="stop_ST:place_censta",
        data={CONF_MODE: MODE_STOP},
    )
    entry.add_to_hass(hass)

    stop_loc = LocationSearchResult(
        LocationId="ST:place_censta", Description="Central station"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"mode": MODE_STOP}
    )

    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            return_value=[stop_loc],
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Duplicate Stop",
                CONF_STOP_NAME: "Central station",
            },
        )

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


async def test_step_reconfigure_journey_same_locations_and_conflict(
    hass: HomeAssistant,
) -> None:
    """Test journey reconfigure when locations remain unchanged or conflict with another entry."""
    entry1 = MockConfigEntry(
        domain=DOMAIN,
        unique_id="journey_ST:place_censta_ST:place_spcsta",
        data={
            CONF_MODE: MODE_JOURNEY,
            CONF_NAME: "Commute 1",
            CONF_START_LOCATION_ID: "ST:place_censta",
            CONF_END_LOCATION_ID: "ST:place_spcsta",
            CONF_START_NAME: "Central station",
            CONF_END_NAME: "Springfield Central",
        },
    )
    entry1.add_to_hass(hass)

    entry2 = MockConfigEntry(
        domain=DOMAIN,
        unique_id="journey_ST:other_ST:dest",
        data={
            CONF_MODE: MODE_JOURNEY,
            CONF_NAME: "Commute 2",
            CONF_START_NAME: "Other",
            CONF_END_NAME: "Dest",
        },
    )
    entry2.add_to_hass(hass)

    start_loc = LocationSearchResult(
        LocationId="ST:place_censta", Description="Central station"
    )
    end_loc = LocationSearchResult(
        LocationId="ST:place_spcsta", Description="Springfield Central"
    )

    # 1. Reconfigure entry1 keeping the exact same locations (branch: new_unique_id == entry.unique_id)
    flow1 = await entry1.start_reconfigure_flow(hass)
    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=[[start_loc], [end_loc]],
        ) as search,
    ):
        res1 = await hass.config_entries.flow.async_configure(
            flow1["flow_id"],
            {
                CONF_START_NAME: "  Central station  ",
                CONF_END_NAME: "Springfield Central",
            },
        )
    search.assert_not_awaited()
    assert res1["type"] is FlowResultType.ABORT
    assert res1["reason"] == "reconfigure_successful"

    # 2. Reconfigure entry2 to point to entry1's locations (conflict with existing entry)
    flow2 = await entry2.start_reconfigure_flow(hass)
    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=[[start_loc], [end_loc]],
        ),
    ):
        res2 = await hass.config_entries.flow.async_configure(
            flow2["flow_id"],
            {
                CONF_START_NAME: "Central station",
                CONF_END_NAME: "Springfield Central",
            },
        )
    assert res2["type"] is FlowResultType.ABORT
    assert res2["reason"] == "already_configured"


async def test_step_reconfigure_stop_same_location_and_conflict(
    hass: HomeAssistant,
) -> None:
    """Test stop reconfigure when location remains unchanged or conflicts with another entry."""
    entry1 = MockConfigEntry(
        domain=DOMAIN,
        unique_id="stop_ST:place_censta",
        data={
            CONF_MODE: MODE_STOP,
            CONF_NAME: "Stop 1",
            CONF_STOP_LOCATION_ID: "ST:place_censta",
            CONF_STOP_NAME: "Central station",
        },
    )
    entry1.add_to_hass(hass)

    entry2 = MockConfigEntry(
        domain=DOMAIN,
        unique_id="stop_ST:other_stop",
        data={
            CONF_MODE: MODE_STOP,
            CONF_NAME: "Stop 2",
            CONF_STOP_NAME: "Other Stop",
        },
    )
    entry2.add_to_hass(hass)

    stop_loc = LocationSearchResult(
        LocationId="ST:place_censta", Description="Central station"
    )

    # 1. Reconfigure entry1 keeping the exact same stop (branch: new_unique_id == entry.unique_id)
    flow1 = await entry1.start_reconfigure_flow(hass)
    with (
        patch(
            "custom_components.translink.client.TranslinkClient.fetch_stop_timetable"
        ) as timetable,
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            return_value=[stop_loc],
        ) as search,
    ):
        res1 = await hass.config_entries.flow.async_configure(
            flow1["flow_id"],
            {CONF_STOP_NAME: "Central station"},
        )
    timetable.assert_not_awaited()
    search.assert_not_awaited()
    assert res1["type"] is FlowResultType.ABORT
    assert res1["reason"] == "reconfigure_successful"

    # Selecting a non-first match already used by another entry aborts.
    original = (entry2.data, entry2.options, entry2.unique_id)
    flow2 = await entry2.start_reconfigure_flow(hass)
    with patch(
        "custom_components.translink.client.TranslinkClient.search_locations",
        return_value=[_ROMA_STREET_RESULTS[2], stop_loc],
    ):
        res2 = await hass.config_entries.flow.async_configure(
            flow2["flow_id"],
            {CONF_STOP_NAME: "Central"},
        )
        assert res2["step_id"] == "stop_select"
        res2 = await hass.config_entries.flow.async_configure(
            flow2["flow_id"], {CONF_STOP_LOCATION_ID: "ST:place_censta"}
        )
    assert res2["type"] is FlowResultType.ABORT
    assert res2["reason"] == "already_configured"
    assert (entry2.data, entry2.options, entry2.unique_id) == original


async def test_reconfigure_journey_confirms_changed_endpoint(
    hass: HomeAssistant,
) -> None:
    """Keep the unchanged endpoint and commit the selected ID with legacy option cleanup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="journey_ST:place_rompl_PL:work",
        data={
            CONF_MODE: MODE_JOURNEY,
            CONF_START_LOCATION_ID: "ST:place_rompl",
            CONF_START_NAME: "Roma Street busway station",
            CONF_END_LOCATION_ID: "PL:work",
            CONF_END_NAME: "Work",
            CONF_TRANSPORT_MODES: ["Train"],
        },
        options={
            CONF_START_LOCATION_ID: "ST:legacy",
            CONF_START_NAME: "Legacy origin",
            CONF_END_LOCATION_ID: "PL:legacy",
            CONF_END_NAME: "Legacy destination",
            CONF_TRANSPORT_MODES: ["Ferry"],
            CONF_SCAN_INTERVAL: 90,
        },
    )
    entry.add_to_hass(hass)
    original = (entry.data, entry.options, entry.unique_id)
    flow = await entry.start_reconfigure_flow(hass)

    with (
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            return_value=_ROMA_STREET_RESULTS,
        ) as search,
        patch.object(hass.config_entries, "async_schedule_reload") as reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                CONF_START_NAME: "Roma Street",
                CONF_END_NAME: "Work",
                CONF_TRANSPORT_MODES: ["Bus"],
            },
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "journey_select"
        markers = list(result["data_schema"].schema)
        assert [marker.schema for marker in markers] == [CONF_START_LOCATION_ID]
        assert markers[0].default() == "ST:place_rompl"
        assert result["description_placeholders"] == {
            "start_query": "Roma Street",
            "end_query": "Work",
        }
        assert (entry.data, entry.options, entry.unique_id) == original
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {CONF_START_LOCATION_ID: "ST:place_romsta"}
        )

    search.assert_awaited_once_with("Roma Street")
    reload.assert_called_once_with(entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == "journey_ST:place_romsta_PL:work"
    assert entry.data[CONF_START_LOCATION_ID] == "ST:place_romsta"
    assert entry.data[CONF_START_NAME] == "Roma Street station"
    assert entry.data[CONF_END_LOCATION_ID] == "PL:work"
    assert entry.data[CONF_END_NAME] == "Work"
    assert entry.data[CONF_TRANSPORT_MODES] == ["Bus"]
    assert entry.options == {CONF_SCAN_INTERVAL: 90}


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (TranslinkConnectionError("Network error"), "cannot_connect"),
        (ValueError("Unexpected planner error"), "unknown"),
    ],
)
async def test_journey_confirmation_can_retry_after_plan_error(
    hass: HomeAssistant, error: Exception, reason: str
) -> None:
    """Show planner errors on the selection form and let the user retry."""
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow_id = flow["flow_id"]
    await hass.config_entries.flow.async_configure(flow_id, {CONF_MODE: MODE_JOURNEY})

    with (
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=[[_ROMA_STREET_RESULTS[2]], _ROMA_STREET_RESULTS],
        ),
        patch(
            "custom_components.translink.client.TranslinkClient.plan_journey",
            side_effect=[error, JourneyPlanResult()],
        ),
        patch("custom_components.translink.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {CONF_START_NAME: "Busway", CONF_END_NAME: "Roma Street"},
        )
        assert result["step_id"] == "journey_select"
        assert [key.schema for key in result["data_schema"].schema] == [
            CONF_END_LOCATION_ID,
        ]
        selection = {CONF_END_LOCATION_ID: "PL:parkland"}
        result = await hass.config_entries.flow.async_configure(flow_id, selection)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "journey_select"
        assert result["errors"] == {"base": reason}
        assert not hass.config_entries.async_entries(DOMAIN)

        result = await hass.config_entries.flow.async_configure(flow_id, selection)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_END_LOCATION_ID] == "PL:parkland"


async def test_stop_selection_handler_rejects_unknown_ids(hass: HomeAssistant) -> None:
    """Reject invalid submissions even when the flow manager's schema is bypassed."""
    flow = TranslinkConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}
    with patch(
        "custom_components.translink.client.TranslinkClient.search_locations",
        return_value=_ROMA_STREET_RESULTS,
    ):
        result = await flow.async_step_stop({CONF_STOP_NAME: "Roma Street"})
    assert result["step_id"] == "stop_select"

    for selection in ({}, {CONF_STOP_LOCATION_ID: "PL:parkland"}):
        result = await flow.async_step_stop_select(selection)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "stop_select"
        assert result["errors"] == {"base": "invalid_location_selection"}


async def test_stop_search_rejects_place_results(hass: HomeAssistant) -> None:
    """A place-only search cannot create a departure board."""
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow_id = flow["flow_id"]
    await hass.config_entries.flow.async_configure(flow_id, {CONF_MODE: MODE_STOP})
    with patch(
        "custom_components.translink.client.TranslinkClient.search_locations",
        return_value=_ROMA_STREET_RESULTS[:2],
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_STOP_NAME: "Roma Street"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "stop"
    assert result["errors"] == {CONF_STOP_NAME: "no_board_location"}


@pytest.mark.parametrize("has_station", [False, True])
async def test_reconfigure_legacy_place_board_searches_again(
    hass: HomeAssistant, has_station: bool
) -> None:
    """Search again for the saved name when the legacy ID cannot be used for a board."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="stop_PL:parkland",
        data={
            CONF_MODE: MODE_STOP,
            CONF_STOP_LOCATION_ID: "PL:parkland",
            CONF_STOP_NAME: "Roma Street Parkland",
        },
        options={CONF_SCAN_INTERVAL: 90},
    )
    entry.add_to_hass(hass)
    original = (entry.data, entry.options, entry.unique_id)
    flow = await entry.start_reconfigure_flow(hass)
    results = _ROMA_STREET_RESULTS[: 3 if has_station else 2]

    with (
        patch(
            "custom_components.translink.client.TranslinkClient.fetch_stop_timetable"
        ) as timetable,
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            return_value=results,
        ) as search,
        patch.object(hass.config_entries, "async_schedule_reload") as reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {CONF_STOP_NAME: "Roma Street Parkland"}
        )

    if has_station:
        timetable.assert_awaited_once_with("ST:place_rompl")
    else:
        timetable.assert_not_awaited()
    search.assert_awaited_once_with("Roma Street Parkland")
    if has_station:
        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_STOP_LOCATION_ID] == "ST:place_rompl"
        assert entry.unique_id == "stop_ST:place_rompl"
        reload.assert_called_once_with(entry.entry_id)
    else:
        assert result["step_id"] == "reconfigure"
        assert result["errors"] == {CONF_STOP_NAME: "no_board_location"}
        assert (entry.data, entry.options, entry.unique_id) == original
        reload.assert_not_called()


async def test_cancel_pending_reconfigure_keeps_entry(hass: HomeAssistant) -> None:
    """Cancel without changing data, options or unique ID."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="stop_ST:place_censta",
        data={
            CONF_MODE: MODE_STOP,
            CONF_STOP_LOCATION_ID: "ST:place_censta",
            CONF_STOP_NAME: "Central station",
        },
        options={CONF_SCAN_INTERVAL: 90},
    )
    entry.add_to_hass(hass)
    original = (entry.data, entry.options, entry.unique_id)
    flow = await entry.start_reconfigure_flow(hass)

    with patch(
        "custom_components.translink.client.TranslinkClient.search_locations",
        return_value=_ROMA_STREET_RESULTS,
    ):
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {CONF_STOP_NAME: "Roma Street"}
        )
    assert result["step_id"] == "stop_select"
    hass.config_entries.flow.async_abort(flow["flow_id"])
    assert (entry.data, entry.options, entry.unique_id) == original


@pytest.mark.parametrize("multiple_matches", [False, True])
async def test_journey_setup_allows_correcting_a_mismatched_region(
    hass: HomeAssistant,
    plan_response_data,
    multiple_matches: bool,
) -> None:
    """Keep a journey with SEQ signals out of the Cairns feed."""
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_MODE: MODE_JOURNEY}
    )
    start = LocationSearchResult(
        LocationId="ST:place_romsta", Description="Roma Street station"
    )
    end = LocationSearchResult(
        LocationId="ST:place_censta", Description="Central station"
    )
    data = {
        CONF_NAME: "Commute",
        CONF_START_NAME: start.name,
        CONF_END_NAME: end.name,
        CONF_REALTIME_REGION: "CNS",
    }
    start_results = _ROMA_STREET_RESULTS if multiple_matches else [start]
    with (
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=[start_results, [end], start_results, [end]],
        ),
        patch(
            "custom_components.translink.client.TranslinkClient.plan_journey",
            return_value=JourneyPlanResult.model_validate(plan_response_data),
        ),
        patch("custom_components.translink.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(flow["flow_id"], data)
        if multiple_matches:
            assert result["step_id"] == "journey_select"
            result = await hass.config_entries.flow.async_configure(
                flow["flow_id"],
                {CONF_START_LOCATION_ID: start.id},
            )
        assert result["step_id"] == "journey"
        assert result["errors"] == {"base": "region_mismatch"}
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {**data, CONF_REALTIME_REGION: "SEQ"},
        )
        if multiple_matches:
            assert result["step_id"] == "journey_select"
            result = await hass.config_entries.flow.async_configure(
                flow["flow_id"],
                {CONF_START_LOCATION_ID: start.id},
            )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_REALTIME_REGION] == "SEQ"


async def test_reconfigure_region_only_preserves_journey_identity_and_options(
    hass: HomeAssistant,
) -> None:
    """Confirm a legacy entry's region without looking up unchanged locations."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="journey_ST:place_cnsstn_ST:place_jcucns",
        data={
            CONF_MODE: MODE_JOURNEY,
            CONF_START_LOCATION_ID: "ST:place_cnsstn",
            CONF_START_NAME: "Cairns City station",
            CONF_END_LOCATION_ID: "ST:place_jcucns",
            CONF_END_NAME: "James Cook University station",
            CONF_TRANSPORT_MODES: ["Bus"],
        },
        options={CONF_SCAN_INTERVAL: 90, CONF_TRANSPORT_MODES: ["Bus"]},
    )
    entry.add_to_hass(hass)
    flow = await entry.start_reconfigure_flow(hass)
    marker = next(
        field
        for field in flow["data_schema"].schema
        if field.schema == CONF_REALTIME_REGION
    )
    assert marker.default() == "SEQ"
    with (
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations"
        ) as search,
        patch.object(hass.config_entries, "async_schedule_reload") as reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                CONF_START_NAME: "Cairns City station",
                CONF_END_NAME: "James Cook University station",
                CONF_TRANSPORT_MODES: ["Bus"],
                CONF_REALTIME_REGION: "CNS",
            },
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == "journey_ST:place_cnsstn_ST:place_jcucns"
    assert entry.options == {CONF_SCAN_INTERVAL: 90, CONF_TRANSPORT_MODES: ["Bus"]}
    assert entry.data[CONF_REALTIME_REGION] == "CNS"
    search.assert_not_called()
    reload.assert_called_once_with(entry.entry_id)


async def _notice_flow(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    form = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MODE: "notices"}
    )
    assert form["type"] is FlowResultType.FORM
    assert form["step_id"] == "notices"
    mode_selector = form["data_schema"].schema["notice_route_mode"]
    assert mode_selector.config["options"] == ["bus", "ferry", "train", "tram"]
    assert mode_selector.config["translation_key"] == "notice_route_mode"
    return form["flow_id"]


@pytest.mark.parametrize(
    ("scope", "suffix", "stored_filter"),
    [
        ("network", "network", {}),
        ("route", "route_RPSP", {"notice_route_id": "RPSP"}),
        ("mode", "mode_Train", {"notice_route_mode": "Train"}),
    ],
)
async def test_notice_config_entry_is_unique_to_network_and_scope(
    hass: HomeAssistant, scope: str, suffix: str, stored_filter: dict[str, str]
) -> None:
    """Only the selected scope filter is saved and used in the unique ID."""
    flow_id = await _notice_flow(hass)
    with (
        patch(
            "custom_components.translink.client.TranslinkClient.fetch_alert_feed",
        ) as fetch,
        patch("custom_components.translink.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {
                CONF_NAME: "Rail notices",
                "notice_network": "CNS",
                "notice_scope": scope,
                "notice_route_id": "  RPSP  ",
                "notice_route_mode": "train",
            },
        )
    fetch.assert_awaited_once_with("CNS")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == f"notices_CNS_{suffix}"
    assert result["data"] == {
        CONF_NAME: "Rail notices",
        CONF_MODE: "notices",
        CONF_SCAN_INTERVAL: 60,
        "notice_network": "CNS",
        "notice_scope": scope,
        **stored_filter,
    }


@pytest.mark.parametrize("bad_route", ["", "foo\x00bar", "x" * 129])
async def test_notice_config_validates_gtfs_route_id_before_fetch(
    hass: HomeAssistant, bad_route: str
) -> None:
    """Empty, nonprintable or oversized route IDs are rejected."""
    flow_id = await _notice_flow(hass)
    with patch(
        "custom_components.translink.client.TranslinkClient.fetch_alert_feed"
    ) as fetch:
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {"notice_scope": "route", "notice_route_id": bad_route},
        )
    assert result["errors"] == {"notice_route_id": "invalid_route_id"}
    fetch.assert_not_awaited()


async def test_notice_config_validation_and_feed_failure(hass: HomeAssistant) -> None:
    """A missing mode and a feed failure each retain an editable form."""
    from custom_components.translink.client import AlertFeedError

    flow_id = await _notice_flow(hass)
    with patch(
        "custom_components.translink.client.TranslinkClient.fetch_alert_feed",
        side_effect=AlertFeedError("Unavailable"),
    ) as fetch:
        result = await hass.config_entries.flow.async_configure(
            flow_id, {"notice_scope": "mode"}
        )
        assert result["errors"] == {"notice_route_mode": "notice_mode_required"}
        fetch.assert_not_awaited()
        result = await hass.config_entries.flow.async_configure(
            flow_id, {"notice_scope": "mode", "notice_route_mode": "tram"}
        )
        assert result["errors"] == {"base": "cannot_connect"}
        fetch.assert_awaited_once_with("SEQ")


async def test_notice_reconfigure_changes_id_and_preserves_scan_interval(
    hass: HomeAssistant,
) -> None:
    """A changed notice scope reloads the entry with new and clean scope data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="notices_SEQ_route_RPSP",
        data={
            CONF_MODE: "notices",
            "notice_network": "SEQ",
            "notice_scope": "route",
            "notice_route_id": "RPSP",
        },
        options={CONF_SCAN_INTERVAL: 120},
    )
    entry.add_to_hass(hass)
    for scope, extra, wanted_id in [
        ("route", {"notice_route_id": "RPSP"}, "notices_SEQ_route_RPSP"),
        ("mode", {"notice_route_mode": "bus"}, "notices_SEQ_mode_Bus"),
    ]:
        form = await entry.start_reconfigure_flow(hass)
        assert form["step_id"] == "notices_reconfigure"
        with (
            patch(
                "custom_components.translink.client.TranslinkClient.fetch_alert_feed"
            ) as fetch,
            patch.object(hass.config_entries, "async_schedule_reload") as reload,
        ):
            result = await hass.config_entries.flow.async_configure(
                form["flow_id"], {"notice_scope": scope, **extra}
            )
        assert result["reason"] == "reconfigure_successful"
        assert entry.unique_id == wanted_id
        assert entry.options == {CONF_SCAN_INTERVAL: 120}
        assert entry.data["notice_scope"] == scope
        fetch.assert_awaited_once_with("SEQ")
        reload.assert_called_once_with(entry.entry_id)
    assert "notice_route_id" not in entry.data
    assert entry.data["notice_route_mode"] == "Bus"

    form = await entry.start_reconfigure_flow(hass)
    mode_field = next(
        field for field in form["data_schema"].schema if field == "notice_route_mode"
    )
    assert mode_field.description["suggested_value"] == "bus"

    options = await hass.config_entries.options.async_init(entry.entry_id)
    assert options["step_id"] == "notices"
    assert set(options["data_schema"]({"scan_interval": 120})) == {"scan_interval"}
    result = await hass.config_entries.options.async_configure(
        options["flow_id"], {CONF_SCAN_INTERVAL: 90}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_SCAN_INTERVAL: 90}


async def test_notice_scope_duplicate_blocks_setup_and_reconfigure(
    hass: HomeAssistant,
) -> None:
    """The same network and scope cannot be configured twice."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="notices_SEQ_network",
        data={CONF_MODE: "notices", "notice_network": "SEQ", "notice_scope": "network"},
    )
    entry.add_to_hass(hass)
    second = MockConfigEntry(
        domain=DOMAIN,
        unique_id="notices_CNS_network",
        data={CONF_MODE: "notices", "notice_network": "CNS", "notice_scope": "network"},
    )
    second.add_to_hass(hass)

    form = await second.start_reconfigure_flow(hass)
    flow_id = await _notice_flow(hass)
    with patch(
        "custom_components.translink.client.TranslinkClient.fetch_alert_feed"
    ) as fetch:
        for current_flow in (form["flow_id"], flow_id):
            result = await hass.config_entries.flow.async_configure(
                current_flow, {"notice_network": "SEQ", "notice_scope": "network"}
            )
            assert result["reason"] == "already_configured"
        fetch.assert_not_awaited()
    assert second.unique_id == "notices_CNS_network"


async def test_loaded_notice_reconfigure_uses_entry_reload_listener(
    hass: HomeAssistant,
) -> None:
    """A loaded notice entry uses its existing Home Assistant reload listener."""
    from unittest.mock import AsyncMock

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="notices_SEQ_network",
        data={CONF_MODE: "notices", "notice_network": "SEQ", "notice_scope": "network"},
    )
    entry.add_to_hass(hass)
    reload = AsyncMock()
    entry.add_update_listener(reload)
    form = await entry.start_reconfigure_flow(hass)
    with patch("custom_components.translink.client.TranslinkClient.fetch_alert_feed"):
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"notice_network": "CNS", "notice_scope": "network"}
        )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    reload.assert_awaited_once_with(hass, entry)
    assert entry.unique_id == "notices_CNS_network"
