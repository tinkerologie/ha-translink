"""Confirmed commute changes trigger automations once."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from custom_components.translink.api.gtfs_realtime import (
    STOP_NO_DATA,
    STOP_SKIPPED,
    TRIP_CANCELED,
    StopTimeUpdateRecord,
    TripUpdateRecord,
)
from custom_components.translink.api.models import (
    JourneyItinerary,
    NoticeItem,
    PlanNotice,
)
from custom_components.translink.window_alerts import (
    AlertLedgerEntry,
    RealtimeIndex,
    evaluate_window_trip,
    observe_window_trip,
)
from custom_components.translink.window_matching import select_window_trips
from custom_components.translink.window_schedule import WindowSchedule

NOW = datetime(2026, 11, 10, 21, 10, tzinfo=UTC)
OCCURRENCE = WindowSchedule.from_config(
    {"window_start": "07:00", "window_end": "08:00", "window_weekdays": ["2"]}
).on(date(2026, 11, 11))
ITINERARY = JourneyItinerary.model_validate(
    {
        "legs": [
            {
                "travelMode": "Bus",
                "tripId": "s_T_61_8_20261111_900",
                "departureTimeUtc": "2026-11-10T21:20:00Z",
                "arrivalTimeUtc": "2026-11-10T21:40:00Z",
                "origin": {"id": "SI:100"},
                "destination": {"id": "SI:101"},
                "legRoute": {"code": "61", "regionId": "T", "regionName": "SEQ"},
            }
        ]
    }
)
TRIP = select_window_trips([ITINERARY], OCCURRENCE, 1)[0]


def _record(**overrides) -> TripUpdateRecord:
    return TripUpdateRecord(
        **{
            "entity_id": "900",
            "trip_id": "900-variant",
            "route_id": "61",
            "start_date": "20261111",
            "timestamp": int(NOW.timestamp()),
            **overrides,
        }
    )


def test_explicit_fresh_cancellation_needs_no_prediction() -> None:
    """Confirm cancellation by relationship and deduplicate it after reload."""
    record = _record(trip_schedule_relationship=TRIP_CANCELED)
    observation = observe_window_trip(TRIP, RealtimeIndex({"900": record}), NOW, {})
    ledger, alerts = evaluate_window_trip(
        observation, AlertLedgerEntry(), threshold=3, step=5
    )
    assert [alert.event_type for alert in alerts] == ["trip_cancelled"]
    assert alerts[0].delay is None

    persisted = AlertLedgerEntry.from_storage(ledger.to_storage())
    assert evaluate_window_trip(observation, persisted, threshold=3, step=5) == (
        persisted,
        (),
    )

    for unconfirmed in (
        _record(trip_schedule_relationship=TRIP_CANCELED, timestamp=None),
        _record(
            trip_schedule_relationship=TRIP_CANCELED,
            timestamp=int((NOW - timedelta(minutes=6)).timestamp()),
        ),
        _record(trip_schedule_relationship=TRIP_CANCELED, start_date="20261110"),
    ):
        observation = observe_window_trip(
            TRIP, RealtimeIndex({"900": unconfirmed}), NOW, {}
        )
        assert (
            evaluate_window_trip(observation, AlertLedgerEntry(), threshold=3, step=5)[
                1
            ]
            == ()
        )


def test_delay_step_recovery_and_unknown_observations() -> None:
    """Keep the alert state through stale and missing feed observations."""
    ledger = AlertLedgerEntry()
    for delay, expected in (
        (2, []),
        (3, ["trip_delayed"]),
        (7, []),
        (8, ["trip_delayed"]),
        (4, []),
        (None, []),
        (8, []),
        (2, []),
        (1, ["trip_recovered"]),
        (-2, []),
        (3, ["trip_delayed"]),
    ):
        realtime = (
            {"900": _record(trip_delay_seconds=delay * 60)} if delay is not None else {}
        )
        observation = observe_window_trip(TRIP, RealtimeIndex(realtime), NOW, {})
        ledger, alerts = evaluate_window_trip(observation, ledger, threshold=3, step=5)
        assert [alert.event_type for alert in alerts] == expected

    stale = _record(
        trip_delay_seconds=0, timestamp=int((NOW - timedelta(minutes=6)).timestamp())
    )
    observation = observe_window_trip(TRIP, RealtimeIndex({"900": stale}), NOW, {})
    assert observation.as_state()["realtime_status"] == "stale"
    assert evaluate_window_trip(observation, ledger, threshold=3, step=5) == (
        ledger,
        (),
    )


def test_unmatched_regions_and_ambiguous_records_stay_unknown() -> None:
    """Keep other regions and colliding trip records out of automation state."""
    record = _record(trip_delay_seconds=300)
    other = _record(entity_id="second", trip_id="900-second", trip_delay_seconds=600)
    route = TRIP.legs[0].legRoute.model_copy(
        update={"regionId": "C", "regionName": "Cairns"}
    )
    wrong_region = replace(
        TRIP, legs=(TRIP.legs[0].model_copy(update={"legRoute": route}),)
    )

    for trip, records in (
        (TRIP, {"first": record, "second": other}),
        (TRIP, {"wrong-route": _record(route_id="999", trip_delay_seconds=300)}),
        (TRIP, {"missing-trip": _record(trip_id=None, trip_delay_seconds=300)}),
        (wrong_region, {"900": record}),
        (replace(TRIP, returned=False), {"900": record}),
        (replace(TRIP, departed=True), {"900": record}),
    ):
        observation = observe_window_trip(trip, RealtimeIndex(records), NOW, {})
        assert observation.status == "unknown"
        assert (
            evaluate_window_trip(observation, AlertLedgerEntry(), threshold=3, step=5)[
                1
            ]
            == ()
        )


def test_scoped_skips_and_no_data() -> None:
    """Accept a required skipped stop and ignore other stops or NO_DATA."""
    for updates, expected in (
        (
            (StopTimeUpdateRecord(stop_id="101", schedule_relationship=STOP_SKIPPED),),
            True,
        ),
        (
            (StopTimeUpdateRecord(stop_id="102", schedule_relationship=STOP_SKIPPED),),
            False,
        ),
        (
            (
                StopTimeUpdateRecord(stop_id="100", schedule_relationship=STOP_NO_DATA),
                StopTimeUpdateRecord(stop_id="101", schedule_relationship=STOP_SKIPPED),
            ),
            False,
        ),
    ):
        record = _record(stop_time_updates=updates)
        observation = observe_window_trip(TRIP, RealtimeIndex({"900": record}), NOW, {})
        assert observation.cancelled is expected


def test_only_relevant_leg_notices_alert_once() -> None:
    """Filter notice timing and scope and deduplicate the persisted public ID."""
    leg = TRIP.legs[0].model_copy(
        update={"notices": [NoticeItem(id=value) for value in (1, 2, 3, 4, 5, 6, None)]}
    )
    trip = replace(TRIP, legs=(leg,))
    notices = {
        str(notice.id): notice
        for notice in (
            PlanNotice(
                id=1,
                title="Reference in this leg",
                startsUtc="2026-11-10T21:05:00Z",
                endsUtc="2026-11-10T21:25:00Z",
            ),
            PlanNotice(id=2, endsUtc="2026-11-10T21:15:00Z"),
            PlanNotice(id=3, startsUtc="2026-11-10T21:25:00Z"),
            PlanNotice(id=4, startsUtc="bad"),
            PlanNotice(id=5, startsUtc="2026-11-10T21:05:00"),
            PlanNotice(id=99, title="Unreferenced notice"),
        )
    }
    realtime = RealtimeIndex({"900": _record(trip_delay_seconds=0)})
    observation = observe_window_trip(trip, realtime, NOW, notices)
    ledger, alerts = evaluate_window_trip(
        observation, AlertLedgerEntry(), threshold=3, step=5
    )
    assert [(alert.event_type, alert.notice.id) for alert in alerts] == [
        ("trip_disruption", 1),
        ("trip_disruption", 6),
    ]
    restored = AlertLedgerEntry.from_storage(ledger.to_storage())
    assert evaluate_window_trip(observation, restored, threshold=3, step=5) == (
        restored,
        (),
    )


def test_transfer_uses_largest_confirmed_boarding_delay_and_ignores_stale_leg() -> None:
    """Keep a confirmed first leg when the transfer is stale."""
    transfer = TRIP.legs[0].model_copy(
        update={
            "tripId": "s_T_61_8_20261111_901",
            "departureTimeUtc": "2026-11-10T21:30:00Z",
        }
    )
    first = _record(trip_delay_seconds=180)
    second = _record(trip_id="901-variant", trip_delay_seconds=600)
    trip = replace(TRIP, legs=(TRIP.legs[0], transfer))
    observation = observe_window_trip(
        trip, RealtimeIndex({"900": first, "901": second}), NOW, {}
    )
    assert observation.delay == 10
    assert observation.trip.effective_departure == TRIP.departure + timedelta(minutes=3)

    second.timestamp = int((NOW - timedelta(minutes=6)).timestamp())
    observation = observe_window_trip(
        trip, RealtimeIndex({"900": first, "901": second}), NOW, {}
    )
    assert observation.status == "confirmed"
    assert observation.delay == 3

    actual_departure = TRIP.departure + timedelta(minutes=3, seconds=1)
    first.timestamp = int(actual_departure.timestamp())
    observation = observe_window_trip(
        trip, RealtimeIndex({"900": first}), actual_departure, {}
    )
    assert observation.trip.departed
    assert observation.delay is None
