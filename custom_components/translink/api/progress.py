"""Pure schedule and GTFS-RT evaluation for the itinerary being followed."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from typing import Literal

from ..const import DEFAULT_REALTIME_REGION, REALTIME_FEED_REGIONS
from .client import (
    _active_transit_leg,
    _baseline_matches,
    _endpoint_prediction,
    _EndpointPrediction,
    _is_public_stop,
    _leg_matches_feed,
    _match_vehicle_position,
    _predicted_boundary,
    _realtime_freshness,
    _stop_key,
    build_calling_stops,
    match_progress_update,
    parse_iso_datetime,
    vehicle_position_is_fresh,
)
from .gtfs_realtime import (
    STOP_SKIPPED,
    TRIP_CANCELED,
    TRIP_DELETED,
    StopTimeUpdateRecord,
    TripUpdateRecord,
    VehiclePositionRecord,
)
from .models import (
    JourneyItinerary,
    JourneyLeg,
    JourneyProgress,
    LegRoute,
    ProgressAction,
    ProgressLeg,
    ProgressStop,
    ProgressTransition,
    StopInfo,
    TrackingBasis,
    TransitionType,
    TripTimetable,
    VehicleStopObservation,
)


def _snapshot_stop(stop: StopInfo | None) -> StopInfo | None:
    if stop is None or not _is_public_stop(stop):
        return None
    return StopInfo(
        id=stop.id, name=stop.name, platform=stop.platform, stopType=stop.stopType
    )


def snapshot_itinerary(itinerary: JourneyItinerary) -> JourneyItinerary:
    """Copy only the public stops and schedule fields needed for progress."""
    return JourneyItinerary(
        legs=[
            JourneyLeg(
                arrivalTimeUtc=leg.arrivalTimeUtc,
                departureTimeUtc=leg.departureTimeUtc,
                origin=_snapshot_stop(leg.origin),
                destination=_snapshot_stop(leg.destination),
                legRoute=(
                    LegRoute(
                        code=route.code,
                        name=route.name,
                        hexColorCode=route.hexColorCode,
                        regionId=route.regionId,
                        regionName=route.regionName,
                    )
                    if (route := leg.legRoute) is not None
                    else None
                ),
                travelMode=leg.travelMode,
                tripId=leg.tripId,
                sameVehicleContinuation=leg.sameVehicleContinuation,
            )
            for leg in itinerary.legs
        ]
    )


def _progress_stop(stop: StopInfo | None) -> ProgressStop | None:
    if stop is None:
        return None
    return ProgressStop(id=stop.id, name=stop.name, platform=stop.platform)


def _journey_id(legs: list[ProgressLeg]) -> str:
    identity = [
        [
            leg.mode,
            leg.trip_id,
            leg.origin.id if leg.origin is not None else None,
            leg.destination.id if leg.destination is not None else None,
            str(leg.scheduled_departure),
            str(leg.scheduled_arrival),
        ]
        for leg in legs
    ]
    return hashlib.sha256(
        json.dumps(identity, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ProgressFeeds:
    """Already fetched data for the selected realtime region."""

    trip_updates: dict[str, TripUpdateRecord] = field(default_factory=dict)
    vehicle_positions: Sequence[VehiclePositionRecord] = ()
    timetables: Mapping[str, TripTimetable] = field(default_factory=dict)
    realtime_region: str = DEFAULT_REALTIME_REGION
    region_confirmed: bool = True


@dataclass(frozen=True)
class _AlightingOccurrence:
    trip_id: str
    sequence: int
    stop_id: str
    stop_name: str | None
    skipped: bool


@dataclass(frozen=True)
class _LegRealtime:
    eligible: bool = False
    strict_identity: bool = False
    conflicting: bool = False
    update: TripUpdateRecord | None = None
    departure: _EndpointPrediction = field(default_factory=_EndpointPrediction)
    arrival: _EndpointPrediction = field(default_factory=_EndpointPrediction)

    @property
    def cancelled(self) -> bool:
        return self.update is not None and self.update.trip_schedule_relationship in (
            TRIP_CANCELED,
            TRIP_DELETED,
        )


@dataclass(frozen=True)
class _VehicleEvidence:
    trip_id: str
    observation: VehicleStopObservation


@dataclass
class ProgressMemory:
    """Evidence scoped to one itinerary, with at most one sample per leg."""

    journey_id: str | None = None
    occurrences: dict[int, _AlightingOccurrence] = field(default_factory=dict)
    observations: dict[int, _VehicleEvidence] = field(default_factory=dict)
    emitted: set[str] = field(default_factory=set)
    predicted_final_arrival: datetime | None = None


@dataclass(frozen=True)
class ProgressResult:
    """Public progress, bounded memory, and the end time for the coordinator."""

    progress: JourneyProgress
    memory: ProgressMemory = field(default_factory=ProgressMemory)
    final_arrival: datetime | None = None


def _leg_realtime(leg: JourneyLeg, feeds: ProgressFeeds, now: datetime) -> _LegRealtime:
    feed = REALTIME_FEED_REGIONS.get(feeds.realtime_region)
    if (
        leg.travelMode.lower() == "walk"
        or feed is None
        or not _leg_matches_feed(leg, feed, feeds.region_confirmed)
    ):
        return _LegRealtime()
    update, conflicting = match_progress_update(
        leg, feeds.trip_updates, strict_identity=feed.strict_identity
    )
    if update is None:
        return _LegRealtime(True, feed.strict_identity, conflicting)
    updated_at, freshness = _realtime_freshness(update, now)
    if freshness != "fresh":
        return _LegRealtime(True, feed.strict_identity, conflicting=True)
    timetable = feeds.timetables.get(leg.tripId or "")
    calls, _, _ = build_calling_stops(leg, timetable, update)
    return _LegRealtime(
        eligible=True,
        strict_identity=feed.strict_identity,
        update=update,
        departure=_endpoint_prediction(
            leg,
            update,
            timetable,
            calls,
            updated_at,
            freshness,
            arrival=False,
            allow_trip_delay=False,
        ),
        arrival=_endpoint_prediction(
            leg,
            update,
            timetable,
            calls,
            updated_at,
            freshness,
            arrival=True,
            allow_trip_delay=False,
        ),
    )


def _alighting_occurrence(
    leg: ProgressLeg, data: _LegRealtime, previous: _AlightingOccurrence | None
) -> _AlightingOccurrence | None:
    stop = leg.destination
    if data.conflicting or not data.eligible or stop is None or not stop.id:
        return None
    update = data.update
    if update is None or not update.trip_id:
        return previous
    if previous is not None and previous.trip_id != update.trip_id:
        previous = None
    destination = _stop_key(stop.id)
    candidates = [
        item
        for item in update.stop_time_updates
        if destination and _stop_key(item.stop_id) == destination
    ]
    if not candidates:
        return previous
    if len(candidates) > 1:
        candidates = [
            item
            for item in candidates
            if _baseline_matches(item, leg.scheduled_arrival, arrival=True)
        ]
    if len(candidates) != 1:
        return None
    candidate: StopTimeUpdateRecord = candidates[0]
    if candidate.stop_sequence is None:
        return None
    arrival = candidate.arrival
    if (
        arrival is not None
        and arrival.time is not None
        and arrival.delay is not None
        and leg.scheduled_arrival is not None
        and not _baseline_matches(candidate, leg.scheduled_arrival, arrival=True)
    ):
        return None
    return _AlightingOccurrence(
        update.trip_id,
        candidate.stop_sequence,
        stop.id,
        stop.name,
        candidate.schedule_relationship == STOP_SKIPPED,
    )


def vehicle_candidates_for_trip(
    positions: Sequence[VehiclePositionRecord],
    trip_id: str,
) -> list[VehiclePositionRecord]:
    """Get all exact-trip records, without relying on their legacy lookup aliases."""
    return [record for record in positions if record.trip_id == trip_id]


def _vehicle_evidence(
    planner_leg: JourneyLeg,
    leg: ProgressLeg,
    data: _LegRealtime,
    occurrence: _AlightingOccurrence | None,
    positions: Sequence[VehiclePositionRecord],
    now: datetime,
) -> tuple[_VehicleEvidence | None, bool]:
    if (
        not data.eligible
        or data.conflicting
        or (data.strict_identity and data.update is None)
    ):
        return None, data.conflicting
    trip_id = (
        data.update.trip_id
        if data.update is not None
        else occurrence.trip_id
        if occurrence is not None
        else leg.trip_id
    )
    if not trip_id:
        return None, False
    candidates = vehicle_candidates_for_trip(positions, trip_id)
    if len(candidates) != 1:
        return None, bool(candidates)
    vehicle, _ = _match_vehicle_position(
        planner_leg,
        candidates,
        now,
        data.update if data.strict_identity else None,
        require_route=True,
    )
    if vehicle is None or vehicle.current_stop_sequence is None:
        return None, True
    assert (
        vehicle.timestamp is not None
    )  # The shared matcher accepted a fresh timestamp.
    stop_id = _stop_key(vehicle.stop_id)
    stop_name = next(
        (
            stop.name
            for stop in (leg.origin, leg.destination)
            if stop is not None and stop_id and _stop_key(stop.id) == stop_id
        ),
        None,
    )
    return _VehicleEvidence(
        trip_id,
        VehicleStopObservation(
            status=vehicle.current_status,
            sequence=vehicle.current_stop_sequence,
            stop_id=vehicle.stop_id,
            stop_name=stop_name,
            observed_at=datetime.fromtimestamp(vehicle.timestamp, UTC),
            fresh=True,
            vehicle_id=vehicle.vehicle_id,
        ),
    ), False


def _confirm_transition(
    leg: ProgressLeg,
    next_leg: ProgressLeg | None,
    next_departure: datetime | None,
    occurrence: _AlightingOccurrence,
    previous: _VehicleEvidence,
    current: _VehicleEvidence,
    memory: ProgressMemory,
    now: datetime,
) -> ProgressTransition | None:
    before, after = previous.observation, current.observation
    if (
        occurrence.skipped
        or not before.vehicle_id
        or before.vehicle_id != after.vehicle_id
        or not before.status
        or not vehicle_position_is_fresh(before.observed_at.timestamp(), now)
        or previous.trip_id != current.trip_id
        or current.trip_id != occurrence.trip_id
        or before.sequence > occurrence.sequence
        or (
            before.sequence == occurrence.sequence
            and (
                before.status not in ("IN_TRANSIT_TO", "INCOMING_AT")
                or _stop_key(before.stop_id) != _stop_key(occurrence.stop_id)
            )
        )
        or after.status != "STOPPED_AT"
        or after.sequence != occurrence.sequence
        or _stop_key(after.stop_id) != _stop_key(occurrence.stop_id)
    ):
        return None
    kind: TransitionType = (
        "transfer_stop_reached" if next_leg is not None else "alighting_stop_reached"
    )
    key = f"{memory.journey_id}:{leg.index}:{kind}"
    if key in memory.emitted:
        return None
    memory.emitted.add(key)
    return ProgressTransition(
        type=kind,
        dedup_key=key,
        leg_index=leg.index,
        stop_id=occurrence.stop_id,
        stop_name=occurrence.stop_name,
        observed_at=after.observed_at,
        next_leg_route=next_leg.route if next_leg is not None else None,
        next_leg_platform=next_leg.origin.platform
        if next_leg and next_leg.origin
        else None,
        next_leg_scheduled_departure=next_leg.scheduled_departure if next_leg else None,
        next_leg_predicted_departure=next_departure,
    )


def _next_transit(legs: list[ProgressLeg], index: int) -> ProgressLeg | None:
    return next((leg for leg in legs[index:] if leg.mode.lower() != "walk"), None)


def _next_action(
    legs: list[ProgressLeg],
    active: int | None,
    transit: int | None,
    realtime: list[_LegRealtime],
    memory: ProgressMemory,
) -> ProgressAction | None:
    kind: Literal["board", "transfer", "alight"]
    if active is None or legs[active].mode.lower() == "walk":
        if transit is None:
            return None
        leg = legs[transit]
        kind = "board"
        stop = leg.origin
        scheduled = leg.scheduled_departure
        next_leg = None
    else:
        leg = legs[active]
        next_leg = _next_transit(legs, active + 1)
        while next_leg is not None and leg.same_vehicle_continuation:
            leg = next_leg
            next_leg = _next_transit(legs, leg.index + 1)
        kind = "transfer" if next_leg is not None else "alight"
        stop = leg.destination
        scheduled = leg.scheduled_arrival
    endpoint = (
        realtime[leg.index].departure
        if kind == "board"
        else realtime[leg.index].arrival
    )
    occurrence = memory.occurrences.get(leg.index)
    skipped = endpoint.relationship == "skipped" or (
        kind != "board" and occurrence is not None and occurrence.skipped
    )
    prediction = _predicted_boundary(scheduled, endpoint) if not skipped else None
    return ProgressAction(
        type=kind,
        leg_index=leg.index,
        stop_id=stop.id if stop else None,
        stop_name=stop.name if stop else None,
        scheduled_time=scheduled,
        predicted_time=prediction,
        time_source="realtime"
        if prediction is not None
        else "scheduled"
        if scheduled is not None
        else "unknown",
        realtime_updated_at=endpoint.updated_at if prediction is not None else None,
        skipped=skipped,
        next_leg_route=next_leg.route if next_leg is not None else None,
        next_leg_platform=next_leg.origin.platform
        if next_leg and next_leg.origin
        else None,
    )


def evaluate_progress(
    itinerary: JourneyItinerary | None,
    *,
    planned_at: datetime,
    now: datetime,
    tracking_basis: TrackingBasis = "planner_first_itinerary",
    feeds: ProgressFeeds | None = None,
    memory: ProgressMemory | None = None,
) -> ProgressResult:
    """Evaluate progress from the selected itinerary at the supplied time."""
    progress = JourneyProgress(planned_at=planned_at, tracking_basis=tracking_basis)
    if itinerary is None:
        progress.state = "no_service"
        return ProgressResult(progress)
    progress.legs = legs = [
        ProgressLeg(
            index=index,
            mode=leg.travelMode,
            route=(route.code or route.name) if (route := leg.legRoute) else None,
            color=route.hexColorCode if route else None,
            trip_id=leg.tripId,
            origin=_progress_stop(leg.origin),
            destination=_progress_stop(leg.destination),
            scheduled_departure=parse_iso_datetime(leg.departureTimeUtc),
            scheduled_arrival=parse_iso_datetime(leg.arrivalTimeUtc),
            same_vehicle_continuation=leg.sameVehicleContinuation,
        )
        for index, leg in enumerate(itinerary.legs)
    ]
    progress.journey_id = _journey_id(legs)
    if not legs:
        return ProgressResult(progress)
    previous = (
        memory
        if memory is not None and memory.journey_id == progress.journey_id
        else ProgressMemory()
    )
    current = ProgressMemory(
        journey_id=progress.journey_id,
        observations=previous.observations.copy(),
        emitted=previous.emitted.copy(),
    )
    feeds = feeds if feeds is not None else ProgressFeeds()
    realtime = [_leg_realtime(leg, feeds, now) for leg in itinerary.legs]
    departures = [
        _predicted_boundary(leg.scheduled_departure, data.departure)
        for leg, data in zip(legs, realtime, strict=True)
    ]
    arrivals = [
        _predicted_boundary(leg.scheduled_arrival, data.arrival)
        for leg, data in zip(legs, realtime, strict=True)
    ]
    final_transit = next(
        (leg for leg in reversed(legs) if leg.mode.lower() != "walk"), None
    )
    if final_transit is not None:
        data = realtime[final_transit.index]
        if arrivals[final_transit.index] is not None:
            current.predicted_final_arrival = arrivals[final_transit.index]
        elif data.update is None:
            current.predicted_final_arrival = previous.predicted_final_arrival
    start = departures[0] or legs[0].scheduled_departure
    end = legs[-1].scheduled_arrival
    if end is not None and current.predicted_final_arrival is not None:
        end = max(end, current.predicted_final_arrival)
    if any(data.cancelled for data in realtime):
        progress.state = "cancelled"
        return ProgressResult(progress, current, end)
    windows = [
        (
            departure or leg.scheduled_departure,
            max(arrival, leg.scheduled_arrival)
            if arrival is not None and leg.scheduled_arrival is not None
            else leg.scheduled_arrival,
        )
        for leg, departure, arrival in zip(legs, departures, arrivals, strict=True)
    ]
    if (
        start is None
        or end is None
        or any(
            leg.scheduled_departure is None
            or leg.scheduled_arrival is None
            or leg.scheduled_departure > leg.scheduled_arrival
            for leg in legs
        )
        or any(
            left.scheduled_arrival > right.scheduled_departure
            for left, right in pairwise(legs)
            if left.scheduled_arrival is not None
            and right.scheduled_departure is not None
        )
    ):
        return ProgressResult(progress, current, end)
    transit, _ = _active_transit_leg(
        itinerary.legs,
        {index: data.arrival for index, data in enumerate(realtime)},
        now,
    )
    active = None
    if now < start:
        progress.state = "not_started"
    elif now > end:
        progress.state = "finished"
    else:
        progress.state = "in_progress"
        active = next(
            (
                index
                for index, (departure, arrival) in enumerate(windows)
                if departure is not None
                and arrival is not None
                and departure <= now <= arrival
                and (legs[index].mode.lower() == "walk" or index == transit)
            ),
            None,
        )
        if active is not None:
            progress.active_leg_index = active
            progress.active_leg_timing_source = (
                "realtime_schedule"
                if departures[active] is not None or arrivals[active] is not None
                else "schedule"
            )
            progress.active_leg_source = progress.active_leg_timing_source
    for index, (planner_leg, leg, data) in enumerate(
        zip(itinerary.legs, legs, realtime, strict=True)
    ):
        occurrence = _alighting_occurrence(leg, data, previous.occurrences.get(index))
        if occurrence is not None:
            current.occurrences[index] = occurrence
        evidence, conflicting = _vehicle_evidence(
            planner_leg, leg, data, occurrence, feeds.vehicle_positions, now
        )
        if evidence is None:
            if conflicting:
                current.observations.pop(index, None)
            continue
        prior = previous.observations.get(index)
        if (
            prior is not None
            and prior.observation.observed_at >= evidence.observation.observed_at
        ):
            if index == active and prior == evidence:
                progress.vehicle_observation = prior.observation
                progress.active_leg_source = "vehicle"
            continue
        if index == active:
            progress.vehicle_observation = evidence.observation
            progress.active_leg_source = "vehicle"
        current.observations[index] = evidence
        next_leg = _next_transit(legs, index + 1)
        departure = windows[index][0]
        if (
            occurrence is not None
            and prior is not None
            and departure is not None
            and departure <= min(now, evidence.observation.observed_at)
            and (next_leg is None or not leg.same_vehicle_continuation)
        ):
            transition = _confirm_transition(
                leg,
                next_leg,
                departures[next_leg.index] if next_leg else None,
                occurrence,
                prior,
                evidence,
                current,
                now,
            )
            if transition is not None:
                progress.transitions.append(transition)
    if progress.state != "finished":
        progress.next_action = _next_action(legs, active, transit, realtime, current)
    return ProgressResult(progress, current, end)
