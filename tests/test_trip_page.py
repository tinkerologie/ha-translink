"""Authentic public timetable evidence and adversarial inert-decoder cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.translink.api import trip_page
from custom_components.translink.api.client import build_journey_summary
from custom_components.translink.api.models import JourneyPlanResult
from custom_components.translink.api.trip_page import (
    TripPageParseError,
    parse_trip_page,
)

ROOT = Path(__file__).parent / "fixtures" / "trip_page"
TRIP_ID = "s_T_RPSP_8_20261026_39766414"


def _page(*parts: str) -> str:
    """Labelled synthetic Flight pushes; no JavaScript is evaluated by tests."""
    return (
        "<body>Page not found<script>eval('ignored')</script>"
        + "".join(
            f"<script>self.__next_f.push({json.dumps([1, part])})</script>"
            for part in parts
        )
        + "</body>"
    )


def _trip(**changes):
    """Small synthetic schema for malformed input and framing tests."""
    return {
        "id": TRIP_ID,
        "headsign": "$undefined",
        "departures": [
            {
                "stopId": "600633",
                "name": "Kippa-Ring",
                "order": 1,
                "scheduledDepartureUtc": "2026-10-26T07:46:00Z",
                "canBoardDebark": "Both",
            },
            {
                "stopId": "600010",
                "name": "Fortitude Valley",
                "order": 2,
                "scheduledDepartureUtc": "2026-10-26T08:39:00Z",
                "canBoardDebark": "Alighting",
            },
        ],
        **changes,
    }


def _record(trip) -> str:
    return "b:" + json.dumps({"trip": trip}, ensure_ascii=False) + "\n"


def test_authentic_schedule_and_leg_slice() -> None:
    """The captured page supplies all calls and selects exactly this journey segment."""
    timetable = parse_trip_page((ROOT / "success.html").read_text(), TRIP_ID)
    assert timetable is not None
    assert len(timetable.departures) == 36
    assert [stop.order for stop in timetable.departures] == list(range(1, 37))
    assert timetable.departures[0].stopId == "600633"
    assert timetable.departures[0].scheduledDepartureUtc == "2026-10-26T07:46:00Z"
    assert (
        timetable.departures[-1].name
        == "Springfield Central station, platform 1, Springfield Central"
    )
    assert timetable.departures[-1].canBoardDebark == "Alighting"
    plan = JourneyPlanResult.model_validate_json(
        (ROOT / "plan_response_trip.json").read_text()
    )
    summary = build_journey_summary(plan, trip_timetables={TRIP_ID: timetable})
    leg = summary.itinerary_legs[0]
    assert leg["callingStopsSource"] == "scheduled"
    assert len(leg["callingStops"]) == 20
    assert leg["callingStops"][1]["name"].startswith("Rothwell")
    assert leg["callingStops"][1]["scheduledTimeUtc"] == "2026-10-26T07:50:00Z"
    assert leg["callingStops"][0]["platform"] == "1"
    assert leg["callingStops"][-1]["platform"] == "3"
    assert all(stop["realtime"] is None for stop in leg["callingStops"])
    assert all(stop["platform"] is None for stop in leg["callingStops"][1:-1])
    assert leg["numberOfStops"] == plan.itineraries[0].legs[0].numberOfStops
    assert leg["skippedStops"] == [
        stop.name for stop in plan.itineraries[0].legs[0].skippedStops
    ]
    assert parse_trip_page((ROOT / "not_found.html").read_text(), "missing") is None


def test_synthetic_utf8_text_and_split_pushes() -> None:
    """Text length is bytes, not characters, and no newline separates model data."""
    payload = "fërry\n'\""
    stream = f"a:T{len(payload.encode()):x},{payload}" + _record(_trip())
    result = parse_trip_page(_page(stream[:12], stream[12:]), TRIP_ID)
    assert result is not None
    assert result.headsign is None
    assert (
        parse_trip_page(
            _page('c:{"messages":{"pages":{"trip":{"title":"Trip"}}}}\n'), TRIP_ID
        )
        is None
    )
    assert (
        parse_trip_page(
            "<script>unrelated()</script><script>self.__next_f.push([0])</script>",
            TRIP_ID,
        )
        is None
    )


@pytest.mark.parametrize(
    "stream",
    [
        "not-a-record",
        "q:{}\n",
        "a:Tz,text",
        "a:T20,short",
        "a:T-1,x",
        "a:[]",
        "a:{bad}\n",
        "a:{}\na:[]\n",
        _record(_trip(id="wrong")),
        _record(_trip(departures="$ref")),
        _record(_trip(departures=[None])),
        _record(_trip(departures=[{"stopId": "$L1"}])),
        _record(
            _trip(
                departures=[
                    {
                        "stopId": "x",
                        "order": 1,
                        "scheduledDepartureUtc": "2026-10-26T07:00:00",
                    }
                ]
            )
        ),
        _record(
            _trip(
                departures=[
                    {
                        "stopId": "x",
                        "order": 2,
                        "scheduledDepartureUtc": "2026-10-26T07:00:00Z",
                    },
                    {
                        "stopId": "y",
                        "order": 2,
                        "scheduledDepartureUtc": "2026-10-26T08:00:00Z",
                    },
                ]
            )
        ),
    ],
)
def test_synthetic_rejections(stream: str) -> None:
    with pytest.raises(TripPageParseError):
        parse_trip_page(_page(stream), TRIP_ID)


@pytest.mark.parametrize(
    "html",
    [
        '<script>self.__next_f.push([1,"x"]',
        '<script>self.__next_f.push([1,"x"]</script>',
        "<script>self.__next_f.push(not_json)</script>",
    ],
)
def test_synthetic_truncated_or_invalid_push(html: str) -> None:
    with pytest.raises(TripPageParseError):
        parse_trip_page(html, TRIP_ID)


def test_synthetic_resource_bounds(monkeypatch) -> None:
    with pytest.raises(TripPageParseError):
        parse_trip_page("x" * (trip_page.TRIP_PAGE_MAX_BYTES + 1), TRIP_ID)
    monkeypatch.setattr(trip_page, "MAX_RECORDS", 1)
    with pytest.raises(TripPageParseError):
        parse_trip_page(_page("a:{}\nb:{}\n"), TRIP_ID)
    monkeypatch.setattr(trip_page, "MAX_DEPTH", 1)
    with pytest.raises(TripPageParseError):
        parse_trip_page(_page(_record(_trip())), TRIP_ID)
    monkeypatch.setattr(trip_page, "MAX_DEPTH", 80)
    monkeypatch.setattr(trip_page, "MAX_NODES", 1)
    with pytest.raises(TripPageParseError):
        parse_trip_page(_page(_record(_trip())), TRIP_ID)


def test_anonymous_preload_hints_from_complete_page() -> None:
    """Full live responses include :HL records absent from trimmed trip fixtures."""
    assert (
        parse_trip_page(
            _page(':HL["/style.css","style"]\n' + _record(_trip())), TRIP_ID
        )
        is not None
    )
    with pytest.raises(TripPageParseError):
        parse_trip_page(_page(':HL["/style.css","style"]'), TRIP_ID)


@pytest.mark.parametrize(
    "stream",
    [
        "a:T",
        "a:T1",
        "a:T1,",
        "a:T2,x",
        "a:{}",
        ":{}\n",
    ],
)
def test_incomplete_record_framing_is_rejected(stream):
    with pytest.raises(TripPageParseError):
        parse_trip_page(_page(stream), TRIP_ID)


def test_identical_record_repetition_cannot_create_ambiguous_trips():
    """Repeated irrelevant records are harmless; repeated trip objects fail closed."""
    assert (
        parse_trip_page(_page("a:{}\na:{}\n" + _record(_trip())), TRIP_ID) is not None
    )
    with pytest.raises(TripPageParseError, match="Unexpected trip identity"):
        parse_trip_page(_page(_record(_trip()) * 2), TRIP_ID)
