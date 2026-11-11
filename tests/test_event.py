"""Tests for Translink event platform."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from custom_components.translink.api.models import JourneyProgress, ProgressTransition
from custom_components.translink.client import JourneySummary, StopSummary
from custom_components.translink.const import (
    CONF_MODE,
    CONF_NAME,
    DOMAIN,
    MODE_JOURNEY,
    MODE_STOP,
)
from custom_components.translink.event import (
    EVENT_TYPE_CLEARED,
    EVENT_TYPE_DISRUPTION,
    TranslinkDisruptionEvent,
    async_setup_entry,
)


class FakeEntry:
    """Fake ConfigEntry for testing."""

    def __init__(self, mode: str = MODE_JOURNEY) -> None:
        self.entry_id = "test_entry_id"
        self.data = {
            CONF_MODE: mode,
            CONF_NAME: "My Journey",
        }
        self.runtime_data = None


class FakeCoordinator:
    """Fake coordinator for event tests."""

    def __init__(
        self, mode: str = MODE_JOURNEY, data: Any = None, *, track_vehicle: bool = False
    ) -> None:
        self.mode = mode
        self.track_vehicle = track_vehicle
        self.data = data
        self.entry = FakeEntry(mode=mode)
        self._listeners: list[Any] = []

    def async_add_listener(self, update_callback: Any, context: Any = None) -> Any:
        self._listeners.append(update_callback)
        return lambda: self._listeners.remove(update_callback)


@pytest.fixture
def sample_journey_summary_with_disruptions() -> JourneySummary:
    """Fixture with a JourneySummary containing disruptions."""
    return JourneySummary(
        status="delayed",
        departure_time=datetime(2026, 10, 6, 9, 30, tzinfo=UTC),
        arrival_time=datetime(2026, 10, 6, 10, 15, tzinfo=UTC),
        disruptions_count=2,
        disruptions=[
            {
                "id": 101,
                "title": "Track Maintenance",
                "description": "Buses replace trains between Petrie and Kippa-Ring.",
                "cause": "MAINTENANCE",
                "effect": "REDUCED_SERVICE",
                "severity": "Minor",
                "route": "Redcliffe Line",
                "leg": "Train",
            },
            {
                "id": 102,
                "title": "Signal Fault",
                "description": "Delays of up to 10 minutes.",
                "cause": "TECHNICAL_PROBLEM",
                "effect": "SIGNIFICANT_DELAYS",
                "severity": "Informative",
            },
        ],
        disruptions_summary="Track Maintenance; Signal Fault",
        disruptions_description="• Track Maintenance: Buses replace trains.\n• Signal Fault: Delays.",
        latest_disruption_title="Track Maintenance",
        latest_disruption_description="Buses replace trains between Petrie and Kippa-Ring.",
    )


async def test_async_setup_entry_journey(
    sample_journey_summary_with_disruptions: JourneySummary,
) -> None:
    """Test async_setup_entry for journey entry using runtime_data."""
    hass = MagicMock()
    entry = FakeEntry(mode=MODE_JOURNEY)
    coordinator = FakeCoordinator(
        mode=MODE_JOURNEY, data=sample_journey_summary_with_disruptions
    )
    entry.runtime_data = coordinator

    added_entities: list[TranslinkDisruptionEvent] = []

    def mock_add_entities(entities: list[TranslinkDisruptionEvent]) -> None:
        added_entities.extend(entities)

    await async_setup_entry(hass, entry, mock_add_entities)  # pyright: ignore[reportArgumentType]

    assert len(added_entities) == 1
    event_entity = added_entities[0]
    assert isinstance(event_entity, TranslinkDisruptionEvent)
    assert event_entity.unique_id == "test_entry_id_disruption"
    assert event_entity.device_info == DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data[CONF_NAME],
        manufacturer="Translink Queensland",
        model="Public Transport Journey",
        entry_type=DeviceEntryType.SERVICE,
    )
    assert event_entity.event_types == [EVENT_TYPE_DISRUPTION, EVENT_TYPE_CLEARED]


async def test_async_setup_entry_fallback_domain_data() -> None:
    """Test async_setup_entry falling back to hass.data[DOMAIN]."""
    hass = MagicMock()
    entry = FakeEntry(mode=MODE_STOP)
    coordinator = FakeCoordinator(mode=MODE_STOP, data=None)
    entry.runtime_data = None
    hass.data = {DOMAIN: {entry.entry_id: coordinator}}

    added_entities: list[TranslinkDisruptionEvent] = []

    def mock_add_entities(entities: list[TranslinkDisruptionEvent]) -> None:
        added_entities.extend(entities)

    await async_setup_entry(hass, entry, mock_add_entities)  # pyright: ignore[reportArgumentType]

    assert len(added_entities) == 1
    event_entity = added_entities[0]
    assert event_entity.device_info == DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data[CONF_NAME],
        manufacturer="Translink Queensland",
        model="Station Departure Board",
        entry_type=DeviceEntryType.SERVICE,
    )


async def test_event_lifecycle_and_triggers(
    sample_journey_summary_with_disruptions: JourneySummary,
) -> None:
    """Test disruption triggers, updates, noop, and clear event transitions."""
    entry = FakeEntry(mode=MODE_JOURNEY)
    coordinator = FakeCoordinator(
        mode=MODE_JOURNEY, data=sample_journey_summary_with_disruptions
    )
    event_entity = TranslinkDisruptionEvent(coordinator, entry)  # pyright: ignore[reportArgumentType]

    triggered_events: list[tuple[str, dict[str, Any] | None]] = []

    def mock_trigger_event(
        event_type: str, event_attributes: dict[str, Any] | None = None
    ) -> None:
        triggered_events.append((event_type, event_attributes))

    event_entity._trigger_event = mock_trigger_event  # type: ignore[method-assign]
    event_entity.async_write_ha_state = MagicMock()

    # 1. Added to hass with existing disruptions
    await event_entity.async_added_to_hass()
    assert len(triggered_events) == 1
    ev_type, ev_data = triggered_events[0]
    assert ev_type == EVENT_TYPE_DISRUPTION
    assert ev_data is not None
    assert ev_data["count"] == 2
    assert ev_data["title"] == "Track Maintenance"
    assert ev_data["cause"] == "MAINTENANCE"
    assert ev_data["severity"] == "Minor"

    # 2. Coordinator update with identical disruptions -> no new event
    event_entity._handle_coordinator_update()
    assert len(triggered_events) == 1

    # 3. Coordinator update with new/changed disruptions
    new_summary = JourneySummary(
        status="delayed",
        disruptions_count=1,
        disruptions=[
            {
                "id": 999,
                "title": "Severe Weather",
                "description": "High winds affecting overhead power.",
                "cause": "WEATHER",
                "effect": "SIGNIFICANT_DELAYS",
            }
        ],
    )
    coordinator.data = new_summary
    event_entity._handle_coordinator_update()
    assert len(triggered_events) == 2
    ev_type2, ev_data2 = triggered_events[1]
    assert ev_type2 == EVENT_TYPE_DISRUPTION
    assert ev_data2 is not None
    assert ev_data2["title"] == "Severe Weather"
    assert ev_data2["cause"] == "WEATHER"

    # 4. Coordinator update with all disruptions cleared
    cleared_summary = JourneySummary(
        status="on_time", disruptions_count=0, disruptions=[]
    )
    coordinator.data = cleared_summary
    event_entity._handle_coordinator_update()
    assert len(triggered_events) == 3
    ev_type3, ev_data3 = triggered_events[2]
    assert ev_type3 == EVENT_TYPE_CLEARED
    assert ev_data3 == {"count": 0, "message": "All service disruptions cleared"}

    # 5. Coordinator update with no data
    coordinator.data = None
    event_entity._handle_coordinator_update()
    assert len(triggered_events) == 3


async def test_event_fallback_title_and_description() -> None:
    """Test disruption event when notice items lack title/description."""
    entry = FakeEntry(mode=MODE_STOP)
    stop_summary = StopSummary(
        stop_id="ST:123",
        stop_name="Central",
        disruptions_count=1,
        disruptions=[
            {
                "id": 555,
                "severity": "Informative",
            }
        ],
    )
    coordinator = FakeCoordinator(mode=MODE_STOP, data=stop_summary)
    event_entity = TranslinkDisruptionEvent(coordinator, entry)  # pyright: ignore[reportArgumentType]

    triggered: list[tuple[str, dict[str, Any] | None]] = []
    event_entity._trigger_event = lambda et, ea=None: triggered.append((et, ea))  # type: ignore[method-assign]
    event_entity.async_write_ha_state = MagicMock()

    await event_entity.async_added_to_hass()
    assert len(triggered) == 1
    assert triggered[0][0] == EVENT_TYPE_DISRUPTION
    assert triggered[0][1] is not None
    assert triggered[0][1]["title"] == "Service Disruption"
    assert triggered[0][1]["description"] is None


@pytest.mark.parametrize("parent_has_hook", [True, False])
async def test_entity_id_changed_delegates_when_available(
    parent_has_hook: bool,
    monkeypatch: pytest.MonkeyPatch,
    sample_journey_summary_with_disruptions: JourneySummary,
) -> None:
    """An in-place rename delegates without replaying active disruptions."""
    from homeassistant.helpers.entity import Entity

    calls: list[str] = []
    if parent_has_hook:
        monkeypatch.setattr(
            Entity,
            "async_entity_id_changed",
            lambda self, old_entity_id: calls.append(old_entity_id),
            raising=False,
        )
    else:
        monkeypatch.delattr(Entity, "async_entity_id_changed", raising=False)
    coordinator = FakeCoordinator(data=sample_journey_summary_with_disruptions)
    event_entity = TranslinkDisruptionEvent(coordinator, FakeEntry())  # pyright: ignore[reportArgumentType]
    trigger = MagicMock()
    monkeypatch.setattr(event_entity, "_trigger_event", trigger)
    await event_entity.async_added_to_hass()
    trigger.assert_called_once()
    disruption_ids = event_entity._last_disruption_ids.copy()
    process = MagicMock(wraps=event_entity._process_disruptions)
    monkeypatch.setattr(event_entity, "_process_disruptions", process)

    event_entity.async_entity_id_changed("event.old_id")

    assert calls == (["event.old_id"] if parent_has_hook else [])
    assert event_entity._last_disruption_ids == disruption_ids
    trigger.assert_called_once()
    process.assert_not_called()


@pytest.mark.parametrize("parent_has_hook", [True, False])
def test_window_event_keeps_state_on_entity_id_change(
    parent_has_hook: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing the entity ID delegates when the Home Assistant hook exists."""
    from homeassistant.helpers.entity import Entity

    from custom_components.translink.event import TranslinkWindowEvent

    hook = MagicMock()
    if parent_has_hook:
        monkeypatch.setattr(Entity, "async_entity_id_changed", hook, raising=False)
    else:
        monkeypatch.delattr(Entity, "async_entity_id_changed", raising=False)
    entity = TranslinkWindowEvent(MagicMock())
    entity.async_entity_id_changed("event.old_window")
    assert hook.call_count == int(parent_has_hook)


async def test_transition_event_only_fires_new_confirmations() -> None:
    """Historical transitions are ignored on setup and updates fire once."""
    now = datetime(2026, 10, 6, 0, 0, tzinfo=UTC)
    transfer = ProgressTransition(
        type="transfer_stop_reached",
        dedup_key="journey:0:transfer_stop_reached",
        leg_index=0,
        stop_id="SI:600321",
        observed_at=now,
        next_leg_route="RPSP",
        next_leg_platform="1",
        next_leg_scheduled_departure=now,
    )
    progress = JourneyProgress(journey_id="journey", transitions=[transfer])
    coordinator = FakeCoordinator(
        data=JourneySummary(progress=progress), track_vehicle=True
    )
    entry = coordinator.entry
    entry.runtime_data = coordinator
    entities = []
    await async_setup_entry(MagicMock(), entry, entities.extend)

    entity = next(
        item
        for item in entities
        if item.unique_id == "test_entry_id_journey_transition"
    )
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    await entity.async_added_to_hass()
    for listener in coordinator._listeners[1:]:
        listener()
    entity._trigger_event.assert_not_called()

    alighting = ProgressTransition(
        type="alighting_stop_reached",
        dedup_key="journey:1:alighting_stop_reached",
        leg_index=1,
        stop_id="SI:600089",
        observed_at=now,
    )
    progress.transitions = [alighting]
    entity._handle_coordinator_update()
    entity._handle_coordinator_update()
    entity._trigger_event.assert_called_once_with(
        "alighting_stop_reached",
        {
            "journey_id": "journey",
            "leg_index": 1,
            "stop_id": "SI:600089",
            "stop_name": None,
            "observed_at": "2026-10-06T00:00:00Z",
        },
    )


async def test_transition_update_ignores_missing_data_and_tracks_a_new_journey(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The transfer payload reports its next service after the journey changes."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    from custom_components.translink.event import TranslinkJourneyTransitionEvent

    delegate_rename = MagicMock()
    monkeypatch.setattr(
        CoordinatorEntity, "async_entity_id_changed", delegate_rename, raising=False
    )
    coordinator = FakeCoordinator(data=None, track_vehicle=True)
    entity = TranslinkJourneyTransitionEvent(coordinator, coordinator.entry)
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity.async_entity_id_changed("event.old_journey_transition")
    delegate_rename.assert_called_once_with("event.old_journey_transition")
    await entity.async_added_to_hass()
    entity._handle_coordinator_update()
    entity._trigger_event.assert_not_called()

    now = datetime(2026, 10, 6, 0, 0, tzinfo=UTC)
    coordinator.data = JourneySummary(
        progress=JourneyProgress(
            journey_id="later",
            transitions=[
                ProgressTransition(
                    type="transfer_stop_reached",
                    dedup_key="later:0:transfer_stop_reached",
                    leg_index=0,
                    stop_id="SI:600321",
                    stop_name="Darra",
                    observed_at=now,
                    next_leg_route="RPSP",
                    next_leg_platform="1",
                    next_leg_scheduled_departure=now,
                    next_leg_predicted_departure=now,
                )
            ],
        )
    )
    entity._handle_coordinator_update()
    entity._trigger_event.assert_called_once_with(
        "transfer_stop_reached",
        {
            "journey_id": "later",
            "leg_index": 0,
            "stop_id": "SI:600321",
            "stop_name": "Darra",
            "observed_at": "2026-10-06T00:00:00Z",
            "next_leg_route": "RPSP",
            "next_leg_platform": "1",
            "next_leg_scheduled_departure": "2026-10-06T00:00:00Z",
            "next_leg_predicted_departure": "2026-10-06T00:00:00Z",
        },
    )
    monkeypatch.setattr(CoordinatorEntity, "async_entity_id_changed", None)
    entity.async_entity_id_changed("event.old_journey_transition")
    delegate_rename.assert_called_once()
