"""Window candidate identity and filtering."""

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

from custom_components.translink.api.models import (
    JourneyItinerary,
    JourneyLeg,
    JourneyPlanResult,
    StopInfo,
)
from custom_components.translink.window_matching import (
    merge_window_trips,
    select_window_trips,
    trip_snapshot,
)
from custom_components.translink.window_schedule import WindowSchedule

FIXTURES = Path(__file__).parent / "fixtures"


def test_window_tracks_earliest_distinct_transit_departures() -> None:
    """Selection is independent of upstream itinerary order."""
    plan = JourneyPlanResult.model_validate_json(
        (FIXTURES / "plan_response.json").read_text()
    )
    schedule = WindowSchedule.from_config(
        {"window_start": "09:00", "window_end": "10:00", "window_weekdays": ["1"]}
    )
    occurrence = schedule.on(date(2026, 10, 6))

    trips = select_window_trips(plan.itineraries, occurrence, 1)
    reverse = select_window_trips(list(reversed(plan.itineraries)), occurrence, 1)
    assert len(trips) == 1
    assert trips[0].departure == datetime(2026, 10, 5, 23, 28, tzinfo=UTC)
    assert trips[0].key == reverse[0].key


def test_select_and_merge_distinguish_transfers_and_missing_candidates() -> None:
    """Keep complete transit identities and mark omitted alternatives unknown."""
    plan = JourneyPlanResult.model_validate_json(
        (FIXTURES / "trip_page" / "plan_response_trip.json").read_text()
    )
    schedule = WindowSchedule.from_config(
        {"window_start": "17:00", "window_end": "19:00", "window_weekdays": ["0"]}
    )
    now = datetime(2026, 10, 26, 7, tzinfo=UTC)
    occurrence = schedule.on(date(2026, 10, 26))
    trips = select_window_trips(plan.itineraries, occurrence, 10)
    assert len(trips) >= 2
    assert len({trip.key for trip in trips}) == len(trips)
    missing = merge_window_trips(trips, trips[1:], now, 10)
    assert len(missing) == len(trips)
    assert missing[0].key == trips[0].key
    assert not missing[0].returned
    assert all(trip.returned for trip in missing[1:])


def test_walks_incomplete_ids_and_exclusive_end_do_not_become_candidates() -> None:
    """Only complete transit legs with an in-window first departure qualify."""
    itinerary = JourneyPlanResult.model_validate_json(
        (FIXTURES / "plan_response.json").read_text()
    ).itineraries[0]
    transit = next(leg for leg in itinerary.legs if leg.travelMode != "Walk")
    plan = [
        JourneyItinerary(legs=[JourneyLeg()]),
        JourneyItinerary(legs=[transit.model_copy(update={"tripId": None})]),
        JourneyItinerary(legs=[transit]),
    ]
    occurrence = WindowSchedule.from_config(
        {"window_start": "09:00", "window_end": "09:43", "window_weekdays": ["1"]}
    ).on(date(2026, 10, 6))
    assert select_window_trips(plan, occurrence, 6) == ()


def test_grace_snapshot_excludes_private_stops_and_departed_trips() -> None:
    """Restrict the restart snapshot to public transit legs that can still run."""
    itinerary = JourneyPlanResult.model_validate_json(
        (FIXTURES / "plan_response.json").read_text()
    ).itineraries[0]
    occurrence = WindowSchedule.from_config(
        {"window_start": "09:00", "window_end": "10:00", "window_weekdays": ["1"]}
    ).on(date(2026, 10, 6))
    trip = select_window_trips([itinerary], occurrence, 1)[0]
    assert trip_snapshot(replace(trip, departed=True)) is None
    private_leg = trip.legs[0].model_copy(
        update={"origin": StopInfo(id="PL:private", name="A private address")}
    )
    assert trip_snapshot(replace(trip, legs=(private_leg,))) is None
