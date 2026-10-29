"""Tests for Translink event platform."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

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

    def __init__(self, mode: str = MODE_JOURNEY, data: Any = None) -> None:
        self.mode = mode
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
    assert event_entity.device_info["model"] == "Public Transport Journey"
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
    assert event_entity.device_info["model"] == "Station Departure Board"


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
def test_entity_id_changed_delegates_when_available(
    parent_has_hook: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The entity opts in to in-place entity ID changes on every release."""
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
    event_entity = TranslinkDisruptionEvent(FakeCoordinator(), FakeEntry())  # pyright: ignore[reportArgumentType]

    event_entity.async_entity_id_changed("event.old_id")

    assert calls == (["event.old_id"] if parent_has_hook else [])
