"""Home Assistant commute polling stays within the configured occurrence."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_state_report_event,
)
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.translink.api.gtfs_realtime import TripUpdateRecord
from custom_components.translink.api.models import JourneyPlanResult
from custom_components.translink.client import TranslinkConnectionError
from custom_components.translink.const import DOMAIN
from custom_components.translink.diagnostics import async_get_config_entry_diagnostics
from custom_components.translink.window_coordinator import (
    WindowCoordinator,
    window_store,
)


@pytest.mark.parametrize("kind", ["once", "recurring"])
async def test_idle_entry_activates_without_early_api_requests(
    hass: HomeAssistant, freezer, kind: str
) -> None:
    """Keep the coordinator asleep until the lead starts, then plan for the start."""
    freezer.move_to("2026-11-10T20:44:59Z")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "mode": "window",
            "start_location_id": "SI:100",
            "start_name": "Origin",
            "end_location_id": "SI:101",
            "end_name": "Destination",
            "window_kind": kind,
            "window_weekdays": ["2"],
            "window_date": "2026-11-11",
            "window_start": "07:00",
            "window_end": "08:00",
        },
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.translink.client.TranslinkClient.plan_journey",
            return_value=JourneyPlanResult(),
        ) as plan,
        patch(
            "custom_components.translink.client.TranslinkClient.fetch_trip_updates"
        ) as realtime,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        coordinator = entry.runtime_data
        assert isinstance(coordinator, WindowCoordinator)
        assert coordinator.data.status == "idle"
        assert coordinator.update_interval is None
        plan.assert_not_awaited()
        realtime.assert_not_awaited()

        activation = datetime(2026, 11, 10, 20, 45, tzinfo=UTC)
        freezer.move_to(activation)
        async_fire_time_changed(hass, activation)
        await hass.async_block_till_done()

        assert coordinator.data.status == "active"
        assert plan.await_count == 1
        assert plan.await_args.kwargs["target_datetime"] == datetime(
            2026, 11, 10, 21, tzinfo=UTC
        )
        assert plan.await_args.kwargs["time_search_mode"] == "LeaveAfter"
        realtime.assert_not_awaited()

        freezer.move_to("2026-11-10T22:00:00Z")
        await coordinator.async_refresh()
        assert coordinator.data.status == ("expired" if kind == "once" else "idle")
        assert coordinator.update_interval is None
        assert plan.await_count == 1
        realtime.assert_not_awaited()
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("changed_selection", [False, True])
async def test_reload_in_grace_respects_transport_selection(
    hass: HomeAssistant, freezer, changed_selection: bool
) -> None:
    """Recover tracked transit facts without a new plan or repeated events."""
    freezer.move_to("2026-11-10T21:19:00Z")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Work trip",
        data={
            "mode": "window",
            "start_location_id": "PL:private",
            "start_name": "Private address",
            "end_location_id": "SI:101",
            "end_name": "Destination",
            "transport_modes": ["Bus", "Train"],
            "window_kind": "once",
            "window_date": "2026-11-11",
            "window_start": "07:00",
            "window_end": "07:21",
        },
    )
    entry.add_to_hass(hass)
    planned = JourneyPlanResult.model_validate(
        {
            "itineraries": [
                {
                    "legs": [
                        {"travelMode": "Walk", "origin": {"name": "Private address"}},
                        {
                            "travelMode": "Bus",
                            "notices": [{"id": 17}],
                            "tripId": "s_T_61_8_20261111_900",
                            "departureTimeUtc": "2026-11-10T21:20:00Z",
                            "arrivalTimeUtc": "2026-11-10T21:40:00Z",
                            "origin": {"id": "SI:100", "name": "Public platform"},
                            "destination": {"id": "SI:101"},
                            "legRoute": {
                                "code": "61",
                                "regionId": "T",
                                "regionName": "SEQ",
                            },
                        },
                    ]
                }
            ],
            "notices": [
                {"id": 17, "title": "Reduced service", "effect": "REDUCED_SERVICE"}
            ],
        }
    )
    observed_changes = []

    @callback
    def capture_change(event):
        old = event.data["old_state"]
        new = event.data["new_state"]
        if old is not None and new is not None and new.entity_id.startswith("event."):
            observed_changes.append(new.attributes)

    async_track_state_change_event(hass, "event.work_trip_trip_changes", capture_change)
    record = TripUpdateRecord(
        entity_id="900",
        trip_id="900-variant",
        route_id="61",
        timestamp=int(datetime.now(UTC).timestamp()),
        start_date="20261111",
        trip_delay_seconds=300,
    )

    with (
        patch(
            "custom_components.translink.client.TranslinkClient.plan_journey",
            return_value=planned,
        ) as plan,
        patch(
            "custom_components.translink.client.TranslinkClient.fetch_trip_updates",
            return_value={"900": record},
        ) as realtime,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = entry.runtime_data
        registry = er.async_get(hass)
        event_id = registry.async_get_entity_id(
            "event", DOMAIN, f"{entry.entry_id}_window_trip"
        )
        assert event_id is not None
        event = hass.states.get(event_id)
        assert event is not None
        assert event.attributes["event_type"] == "trip_disruption"
        assert event.attributes["notice_id"] == 17
        assert [data["event_type"] for data in observed_changes] == [
            "trip_delayed",
            "trip_disruption",
        ]
        assert observed_changes[0]["delay_minutes"] == 5

        states = {
            entity.unique_id
            for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        }
        assert states == {
            f"{entry.entry_id}_window_{suffix}"
            for suffix in ("status", "next_start", "tracked_trips", "trip")
        }
        store = window_store(hass, entry.entry_id)
        snapshot = await store.async_load()
        assert snapshot and len(snapshot["trips"]) == 1
        assert "Private address" not in repr(snapshot)
        assert "PL:private" not in repr(snapshot)
        assert "Public platform" not in repr(snapshot)
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["data"]["ledger"] == {"trip_count": 1}
        assert diagnostics["data"]["trips"][0]["realtime_status"] == "confirmed"
        assert "Private address" not in repr(diagnostics)

        freezer.move_to("2026-11-10T21:19:30Z")
        plan.side_effect = TranslinkConnectionError("planner unavailable")
        await coordinator.async_refresh()
        assert coordinator.last_update_success is False
        assert len(observed_changes) == 2
        assert coordinator.ledger_size == 1
        plan.side_effect = None

        freezer.move_to("2026-11-10T21:22:00Z")
        record.timestamp = int(datetime.now(UTC).timestamp())
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                "transport_modes": ["Ferry"]
                if changed_selection
                else ["Train", "Bus", "Bus"],
            },
        )
        await hass.async_block_till_done()
        coordinator = entry.runtime_data
        if changed_selection:
            assert coordinator.data.status == "expired"
            assert coordinator.data.trips == ()
            assert coordinator.ledger_size == 0
            assert plan.await_count == 2
            assert realtime.await_count == 1
            await hass.config_entries.async_remove(entry.entry_id)
            return
        assert coordinator.data.status == "active"
        assert coordinator.data.alerts == ()
        assert plan.await_count == 2
        assert realtime.await_count == 2

        realtime.side_effect = TranslinkConnectionError("feed unavailable")
        await coordinator.async_refresh()
        assert coordinator.data.trips[0].status == "unknown"
        assert coordinator.data.alerts == ()
        realtime.side_effect = None

        freezer.move_to("2026-11-10T21:23:00Z")
        record.timestamp = int(datetime.now(UTC).timestamp())
        record.trip_delay_seconds = 600
        reports = []
        unsubscribe = async_track_state_report_event(hass, event_id, reports.append)
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        unsubscribe()
        assert reports == []
        event = hass.states.get(event_id)
        assert event is not None
        assert event.attributes["event_type"] == "trip_delayed"
        assert event.attributes["delay_minutes"] == 10
        assert event.attributes["previous_delay_minutes"] == 5
        assert plan.await_count == 2

        freezer.move_to("2026-11-10T22:21:00Z")
        await coordinator.async_refresh()
        assert coordinator.data.status == "expired"
        assert realtime.await_count == 4

        await hass.config_entries.async_remove(entry.entry_id)
        assert await store.async_load() is None


@pytest.mark.parametrize(
    "cutoff", ["window_end", "plan_grace", "feed_grace", "early_departure"]
)
async def test_window_refresh_stops_at_the_current_deadline(
    hass: HomeAssistant, freezer, cutoff: str
) -> None:
    """In-flight results cannot start new requests or emit after the cutoff."""
    freezer.move_to("2026-11-10T21:19:00Z")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "mode": "window",
            "start_location_id": "SI:100",
            "start_name": "Origin",
            "end_location_id": "SI:101",
            "end_name": "Destination",
            "window_kind": "once",
            "window_date": "2026-11-11",
            "window_start": "07:00",
            "window_end": "07:21",
        },
    )
    entry.add_to_hass(hass)
    planned = JourneyPlanResult.model_validate(
        {
            "itineraries": [
                {
                    "legs": [
                        {
                            "travelMode": "Bus",
                            "tripId": "900",
                            "departureTimeUtc": "2026-11-10T21:20:00Z",
                            "origin": {"id": "SI:100"},
                            "destination": {"id": "SI:101"},
                        }
                    ]
                }
            ],
        }
    )

    async def plan_journey(**_kwargs):
        if cutoff == "window_end":
            freezer.move_to("2026-11-10T21:21:00Z")
        elif cutoff == "plan_grace":
            freezer.move_to("2026-11-10T22:21:00Z")
        return planned

    async def fetch_realtime(*_args, **_kwargs):
        if cutoff == "feed_grace":
            freezer.move_to("2026-11-10T22:21:00Z")
        delay = 0 if datetime.now(UTC).minute == 22 else 300
        return {
            "900": TripUpdateRecord(
                "900",
                "900",
                None,
                start_date="20261111",
                timestamp=int(datetime.now(UTC).timestamp()),
                trip_delay_seconds=delay,
            )
        }

    with (
        patch(
            "custom_components.translink.client.TranslinkClient.plan_journey",
            side_effect=plan_journey,
        ) as plan,
        patch(
            "custom_components.translink.client.TranslinkClient.fetch_trip_updates",
            side_effect=fetch_realtime,
        ) as feed,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        coordinator = entry.runtime_data
        if cutoff == "early_departure":
            assert coordinator.data.status == "active"
            freezer.move_to("2026-11-10T21:22:00Z")
            await coordinator.async_refresh()

        assert coordinator.data.status == "expired"
        assert coordinator.data.alerts == ()
        assert plan.await_count == 1
        assert (
            feed.await_count
            == {
                "window_end": 0,
                "plan_grace": 0,
                "feed_grace": 1,
                "early_departure": 2,
            }[cutoff]
        )
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("disabled", [True, False])
async def test_window_activation_respects_polling_preferences_and_shutdown(
    hass: HomeAssistant, freezer, disabled: bool
) -> None:
    """Suppress automatic requests while polling is disabled or HA is stopping."""
    freezer.move_to("2026-11-10T20:44:59Z")
    entry = MockConfigEntry(
        domain=DOMAIN,
        pref_disable_polling=disabled,
        data={
            "mode": "window",
            "start_location_id": "SI:100",
            "start_name": "Origin",
            "end_location_id": "SI:101",
            "end_name": "Destination",
            "window_kind": "once",
            "window_date": "2026-11-11",
            "window_start": "07:00",
            "window_end": "08:00",
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.translink.client.TranslinkClient.plan_journey"
    ) as plan:
        assert await hass.config_entries.async_setup(entry.entry_id)
        activation = datetime(2026, 11, 10, 20, 45, tzinfo=UTC)
        freezer.move_to(activation)
        with patch.object(hass, "is_stopping", not disabled):
            async_fire_time_changed(hass, activation)
            await hass.async_block_till_done()
        assert entry.runtime_data.data.status == "idle"
        plan.assert_not_awaited()
        assert await hass.config_entries.async_unload(entry.entry_id)
