"""Tests for Translink config flow and options flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant.common import MockConfigEntry

from custom_components.translink.client import (
    JourneyPlanResult,
    LocationSearchResult,
    TranslinkApiError,
    TranslinkConnectionError,
)
from custom_components.translink.config_flow import TranslinkConfigFlow
from custom_components.translink.const import (
    CONF_END_NAME,
    CONF_MODE,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_START_NAME,
    CONF_STOP_NAME,
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
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            return_value=[stop_loc],
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

    assert result3["type"] is FlowResultType.CREATE_ENTRY
    assert result3["title"] == "Roma Street"
    assert result3["data"][CONF_MODE] == MODE_STOP
    assert result3["data"]["stop_location_id"] == "ST:place_romsta"


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
    """Test journey setup aborts when unique_id is already configured."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="journey_ST:place_censta_ST:place_spcsta",
        data={CONF_MODE: MODE_JOURNEY},
    )
    entry.add_to_hass(hass)

    start_loc = LocationSearchResult(
        LocationId="ST:place_censta", Description="Central station"
    )
    end_loc = LocationSearchResult(
        LocationId="ST:place_spcsta", Description="Springfield Central"
    )
    plan_mock = JourneyPlanResult()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"mode": MODE_JOURNEY}
    )

    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            side_effect=[[start_loc], [end_loc]],
        ),
        patch(
            "custom_components.translink.client.TranslinkClient.plan_journey",
            return_value=plan_mock,
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Duplicate Commute",
                CONF_START_NAME: "Central station",
                CONF_END_NAME: "Springfield Central",
            },
        )

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


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
        ),
    ):
        res1 = await hass.config_entries.flow.async_configure(
            flow1["flow_id"],
            {
                CONF_START_NAME: "Central station",
                CONF_END_NAME: "Springfield Central",
            },
        )
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
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            return_value=[stop_loc],
        ),
    ):
        res1 = await hass.config_entries.flow.async_configure(
            flow1["flow_id"],
            {CONF_STOP_NAME: "Central station"},
        )
    assert res1["type"] is FlowResultType.ABORT
    assert res1["reason"] == "reconfigure_successful"

    # 2. Reconfigure entry2 to point to entry1's stop (conflict)
    flow2 = await entry2.start_reconfigure_flow(hass)
    with (
        patch("custom_components.translink.config_flow.async_get_clientsession"),
        patch(
            "custom_components.translink.client.TranslinkClient.search_locations",
            return_value=[stop_loc],
        ),
    ):
        res2 = await hass.config_entries.flow.async_configure(
            flow2["flow_id"],
            {CONF_STOP_NAME: "Central station"},
        )
    assert res2["type"] is FlowResultType.ABORT
    assert res2["reason"] == "already_configured"
