"""Stable identities for transit itineraries within a commute window."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from typing import Any

from .api.client import parse_iso_datetime
from .api.models import JourneyItinerary, JourneyLeg
from .window_schedule import WindowOccurrence


@dataclass(frozen=True, slots=True)
class WindowTrip:
    """A tracked itinerary with a stable identity and effective departure."""

    key: str
    legs: tuple[JourneyLeg, ...]
    departure: datetime
    effective_departure: datetime
    returned: bool = True
    departed: bool = False

    @property
    def route(self) -> str:
        """Return the first transit route for presentation."""
        leg = self.legs[0]
        route = leg.legRoute
        return (route.code or route.name or leg.travelMode) if route else leg.travelMode


def _window_trip(itinerary: JourneyItinerary) -> WindowTrip | None:
    legs = tuple(leg for leg in itinerary.legs if leg.travelMode.lower() != "walk")
    identity = []
    departures = []
    for leg in legs:
        departure = parse_iso_datetime(leg.departureTimeUtc)
        if not (
            departure
            and leg.tripId
            and leg.origin
            and leg.origin.id
            and leg.destination
            and leg.destination.id
        ):
            return None
        identity.append(
            (leg.tripId, leg.origin.id, leg.destination.id, departure.isoformat())
        )
        departures.append(departure)

    if not departures:
        return None
    key = sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
    return WindowTrip(key, legs, departures[0], departures[0])


def _trip_order(trip: WindowTrip) -> tuple[datetime, str]:
    return trip.departure, trip.key


def select_window_trips(
    itineraries: Iterable[JourneyItinerary],
    occurrence: WindowOccurrence,
    limit: int,
) -> tuple[WindowTrip, ...]:
    """Filter, deduplicate and bound alternatives by first transit departure."""
    candidates: dict[str, WindowTrip] = {}
    for itinerary in itineraries:
        trip = _window_trip(itinerary)
        if trip is not None and occurrence.start <= trip.departure < occurrence.end:
            candidates.setdefault(trip.key, trip)
    return tuple(sorted(candidates.values(), key=_trip_order)[:limit])


def merge_window_trips(
    previous: tuple[WindowTrip, ...],
    returned: tuple[WindowTrip, ...],
    now: datetime,
    limit: int,
) -> tuple[WindowTrip, ...]:
    """Keep unresolved candidates and mark plan omissions as unknown."""
    tracked = {trip.key: trip for trip in previous}
    next_trips = {
        trip.key: replace(
            trip,
            returned=False,
            departed=trip.departed or now > trip.effective_departure,
        )
        for trip in previous
    }
    for trip in returned:
        if (existing := tracked.get(trip.key)) is not None:
            trip = replace(
                trip,
                effective_departure=existing.effective_departure,
                departed=existing.departed,
            )
        next_trips[trip.key] = trip

    # Free capacity from departed trips first as the planner advances through the window.
    eligible = sorted(
        next_trips.values(), key=lambda trip: (trip.departed, *_trip_order(trip))
    )
    return tuple(sorted(eligible[:limit], key=_trip_order))


def trip_snapshot(trip: WindowTrip) -> dict[str, Any] | None:
    """Save just public transit facts required to resume grace polling."""
    if trip.departed:
        return None

    legs: list[dict[str, Any]] = []
    for leg in trip.legs:
        origin = leg.origin.id if leg.origin else None
        destination = leg.destination.id if leg.destination else None
        if not (
            origin
            and origin.startswith("SI:")
            and destination
            and destination.startswith("SI:")
        ):
            return None
        route = leg.legRoute
        legs.append(
            {
                "tripId": leg.tripId,
                "departureTimeUtc": leg.departureTimeUtc,
                "arrivalTimeUtc": leg.arrivalTimeUtc,
                "travelMode": leg.travelMode,
                "origin": {"id": origin},
                "destination": {"id": destination},
                "legRoute": {
                    "code": route.code,
                    "regionId": route.regionId,
                    "regionName": route.regionName,
                }
                if route
                else None,
                "notices": [{"id": notice.id} for notice in leg.notices],
            }
        )

    return {
        "key": trip.key,
        "legs": legs,
        "departure": trip.departure.isoformat(),
        "effective_departure": trip.effective_departure.isoformat(),
        "returned": trip.returned,
    }


def restore_trip(snapshot: Mapping[str, Any]) -> WindowTrip:
    """Restore a grace candidate without its original journey plan."""
    return WindowTrip(
        snapshot["key"],
        tuple(JourneyLeg.model_validate(leg) for leg in snapshot["legs"]),
        datetime.fromisoformat(snapshot["departure"]),
        datetime.fromisoformat(snapshot["effective_departure"]),
        returned=snapshot["returned"],
    )
