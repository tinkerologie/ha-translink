"""Data update coordinator for the Translink integration."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api.client import stop_disruption_fields
from .api.models import (
    JourneyItinerary,
    NoticeSummary,
    StopDepartureItem,
    StopDeparturePlatformChange,
    StopTimetable,
    TimetableDeparture,
    TimetableRoute,
)
from .api.notices import build_notice_summary
from .api.progress import (
    ProgressFeeds,
    ProgressMemory,
    evaluate_progress,
    snapshot_itinerary,
)
from .client import (
    JourneyPlanResult,
    JourneySummary,
    StopSummary,
    TranslinkApiError,
    TranslinkClient,
    TripTimetable,
    build_journey_summary,
    parse_iso_datetime,
)
from .const import (
    AVAILABLE_TRANSPORT_MODES,
    CONF_END_LOCATION_ID,
    CONF_END_NAME,
    CONF_FARE_PREFERENCE,
    CONF_MAX_WALKING_DISTANCE,
    CONF_MODE,
    CONF_NOTICE_NETWORK,
    CONF_NOTICE_ROUTE_ID,
    CONF_NOTICE_ROUTE_MODE,
    CONF_NOTICE_SCOPE,
    CONF_SCAN_INTERVAL,
    CONF_START_LOCATION_ID,
    CONF_START_NAME,
    CONF_STOP_LOCATION_ID,
    CONF_STOP_NAME,
    CONF_TIME_SEARCH_MODE,
    CONF_TRACK_VEHICLE,
    CONF_TRANSPORT_MODES,
    CONF_WALKING_SPEED,
    DEFAULT_FARE_PREFERENCE,
    DEFAULT_MAX_WALKING_DISTANCE,
    DEFAULT_MODE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIME_SEARCH_MODE,
    DEFAULT_TRACK_VEHICLE,
    DEFAULT_TRANSPORT_MODES,
    DEFAULT_WALKING_SPEED,
    DOMAIN,
    JOURNEY_PROGRESS_GRACE_SECONDS,
    MIN_SCAN_INTERVAL,
    MODE_JOURNEY,
    MODE_NOTICES,
    NOTICE_ROUTE_TYPES,
    REALTIME_REGION_NONE,
    TRIP_PAGE_CACHE_LIMIT,
    TRIP_PAGE_MAX_PER_REFRESH,
    TRIP_PAGE_NEGATIVE_TTL,
    TRIP_PAGE_SUCCESS_TTL,
    resolve_realtime_region,
)

_LOGGER = logging.getLogger(__name__)


def _describe_error(err: BaseException) -> str:
    """Return the exception type and message, so an empty message stays readable."""
    message = str(err)
    return f"{type(err).__name__}: {message}" if message else type(err).__name__


def _timetable_vehicle(
    routes: list[TimetableRoute], route_id: str | None
) -> str | None:
    """Resolve a mode from consistent route lines, then the route ID."""
    line_modes = {
        line.vehicleType.casefold()
        for route in routes
        for line in route.lines or ()
        if line.vehicleType
    }
    known_modes = {mode.casefold(): mode for mode in AVAILABLE_TRANSPORT_MODES}
    if len(line_modes) == 1:
        vehicle = known_modes.get(next(iter(line_modes)))
        if vehicle is not None:
            return vehicle

    parts = route_id.split(":", maxsplit=2) if route_id else []
    if len(parts) == 3 and parts[0] == "T":
        return known_modes.get(parts[1].casefold())
    return None


def _stop_visit_row(
    departure: TimetableDeparture,
    routes: list[TimetableRoute],
    vehicle: str | None,
    visit_id: str,
) -> StopDepartureItem:
    """Keep the upstream schedule and realtime fields independent."""
    short_name = next((route.shortName for route in routes if route.shortName), None)
    code = next((route.code for route in routes if route.code), None)
    route_id = departure.routeId
    route_label = (
        short_name or code or (route_id.rsplit(":", 1)[-1] if route_id else "")
    )
    realtime = departure.realtime
    expected = realtime.expectedDepartureUtc if realtime is not None else None
    platform_change = realtime.platformChange if realtime is not None else None

    return StopDepartureItem(
        route=route_label or "Transit",
        vehicle=vehicle,
        headsign=departure.headsign,
        departure_time=departure.scheduledDepartureUtc,
        platform=departure.departurePlatform,
        trip_id=departure.id,
        visit_id=visit_id,
        route_id=route_id,
        direction=departure.direction,
        boarding=departure.canBoardDebark,
        scheduled_departure_time=departure.scheduledDepartureUtc,
        expected_departure_time=expected,
        time_source="realtime" if expected is not None else "scheduled",
        is_cancelled=realtime.isCancelled if realtime is not None else None,
        is_skipped=realtime.isSkipped if realtime is not None else None,
        is_extra=realtime.isExtra if realtime is not None else None,
        platform_change=(
            StopDeparturePlatformChange(
                platform=platform_change.platform,
                old_platform=platform_change.oldPlatform,
                is_source=platform_change.isSource,
            )
            if platform_change is not None
            else None
        ),
        route_color=next(
            (route.routeHexColor for route in routes if route.routeHexColor), None
        ),
    )


def _stop_board_rows(
    timetable: StopTimetable, modes: list[str]
) -> tuple[list[StopDepartureItem], list[StopDepartureItem]]:
    """Split alighting-only visits and deduplicate within each view."""
    routes_by_id: dict[str, list[TimetableRoute]] = defaultdict(list)
    for route in timetable.routes:
        routes_by_id[route.id].append(route)

    visits: dict[
        tuple[bool, str], tuple[TimetableDeparture, list[TimetableRoute], str | None]
    ] = {}
    for index, departure in enumerate(timetable.departures):
        routes = [
            route
            for route in routes_by_id.get(departure.routeId or "", ())
            if departure.direction is None or route.direction == departure.direction
        ]
        vehicle = _timetable_vehicle(routes, departure.routeId)
        if modes and vehicle is not None and vehicle not in modes:
            continue

        visit_id = (
            json.dumps(
                (
                    departure.id,
                    departure.scheduledDepartureUtc,
                    departure.departurePlatform,
                ),
                separators=(",", ":"),
            )
            if (
                departure.id
                and departure.scheduledDepartureUtc
                and departure.departurePlatform
            )
            else f"unidentified:{index}"
        )
        key = departure.canBoardDebark == "Alighting", visit_id
        previous = visits.get(key)
        if previous is None or (
            previous[0].realtime is None and departure.realtime is not None
        ):
            visits[key] = departure, routes, vehicle

    ordered = sorted(
        visits.items(),
        key=lambda item: (
            parse_iso_datetime(item[1][0].scheduledDepartureUtc)
            or datetime.max.replace(tzinfo=UTC)
        ),
    )
    departures: list[StopDepartureItem] = []
    arrivals: list[StopDepartureItem] = []
    for (alighting_only, visit_id), (departure, routes, vehicle) in ordered:
        board = arrivals if alighting_only else departures
        board.append(_stop_visit_row(departure, routes, vehicle, visit_id))
    return departures, arrivals


@dataclass(frozen=True)
class _FollowedJourney:
    """One sanitized itinerary and its in-memory progress evidence."""

    itinerary: JourneyItinerary
    planned_at: datetime
    memory: ProgressMemory

    def has_departed(self, now: datetime) -> bool:
        """Pin only journeys with a scheduled start and end."""
        legs = self.itinerary.legs
        start = parse_iso_datetime(legs[0].departureTimeUtc)
        end = parse_iso_datetime(legs[-1].arrivalTimeUtc)
        return start is not None and end is not None and start <= now


class TranslinkCoordinator(
    DataUpdateCoordinator[JourneySummary | StopSummary | NoticeSummary]
):
    """Coordinator to fetch and update data from Translink Queensland."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.mode = entry.data.get(CONF_MODE, DEFAULT_MODE)
        self.realtime_region, self.region_confirmed = resolve_realtime_region(
            entry.data
        )

        # Configurable scan interval
        scan_seconds = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        scan_seconds = max(MIN_SCAN_INTERVAL, int(scan_seconds))

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=scan_seconds),
        )

        session = async_get_clientsession(hass)
        self.client = TranslinkClient(session=session)
        self._trip_cache: dict[str, tuple[float, TripTimetable | None]] = {}
        self._followed_journey: _FollowedJourney | None = None

    @property
    def start_location_id(self) -> str:
        """Return origin location ID."""
        return str(
            self.entry.options.get(
                CONF_START_LOCATION_ID,
                self.entry.data.get(CONF_START_LOCATION_ID, ""),
            )
        )

    @property
    def start_name(self) -> str:
        """Return origin name."""
        return str(
            self.entry.options.get(
                CONF_START_NAME,
                self.entry.data.get(CONF_START_NAME, ""),
            )
        )

    @property
    def end_location_id(self) -> str:
        """Return destination location ID."""
        return str(
            self.entry.options.get(
                CONF_END_LOCATION_ID,
                self.entry.data.get(CONF_END_LOCATION_ID, ""),
            )
        )

    @property
    def end_name(self) -> str:
        """Return destination name."""
        return str(
            self.entry.options.get(
                CONF_END_NAME,
                self.entry.data.get(CONF_END_NAME, ""),
            )
        )

    @property
    def transport_modes(self) -> list[str]:
        """Return selected transport modes."""
        return list(
            self.entry.options.get(
                CONF_TRANSPORT_MODES,
                self.entry.data.get(CONF_TRANSPORT_MODES, DEFAULT_TRANSPORT_MODES),
            )
        )

    @property
    def time_search_mode(self) -> str:
        """Return time search mode (LeaveAfter / ArriveBefore)."""
        return str(
            self.entry.options.get(
                CONF_TIME_SEARCH_MODE,
                self.entry.data.get(CONF_TIME_SEARCH_MODE, DEFAULT_TIME_SEARCH_MODE),
            )
        )

    @property
    def max_walking_distance(self) -> int:
        """Return max walking distance in meters."""
        return int(
            self.entry.options.get(
                CONF_MAX_WALKING_DISTANCE,
                self.entry.data.get(
                    CONF_MAX_WALKING_DISTANCE, DEFAULT_MAX_WALKING_DISTANCE
                ),
            )
        )

    @property
    def walking_speed(self) -> str:
        """Return walking speed."""
        return str(
            self.entry.options.get(
                CONF_WALKING_SPEED,
                self.entry.data.get(CONF_WALKING_SPEED, DEFAULT_WALKING_SPEED),
            )
        )

    @property
    def fare_preference(self) -> str:
        """Return fare preference."""
        return str(
            self.entry.options.get(
                CONF_FARE_PREFERENCE,
                self.entry.data.get(CONF_FARE_PREFERENCE, DEFAULT_FARE_PREFERENCE),
            )
        )

    @property
    def track_vehicle(self) -> bool:
        """Return whether live vehicle tracking is enabled."""
        return bool(
            self.entry.options.get(
                CONF_TRACK_VEHICLE,
                self.entry.data.get(CONF_TRACK_VEHICLE, DEFAULT_TRACK_VEHICLE),
            )
        )

    async def _async_update_data(self) -> JourneySummary | StopSummary | NoticeSummary:
        """Fetch updated data from Translink."""
        try:
            if self.mode == MODE_JOURNEY:
                return await self._async_update_journey()
            if self.mode == MODE_NOTICES:
                return await self._async_update_notices()
            return await self._async_update_stop()
        except TranslinkApiError as err:
            raise UpdateFailed(
                f"Translink update failed: {str(err) or type(err).__name__}"
            ) from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching Translink data")
            raise UpdateFailed(
                f"Unexpected error fetching Translink data: {_describe_error(err)}"
            ) from err

    async def _async_update_notices(self) -> NoticeSummary:
        """Refresh the configured regional alert scope independently."""
        data = self.entry.data
        network = data[CONF_NOTICE_NETWORK]
        scope = data[CONF_NOTICE_SCOPE]
        value: str | int | None = None
        if scope == "route":
            value = data[CONF_NOTICE_ROUTE_ID]
        elif scope == "mode":
            value = NOTICE_ROUTE_TYPES[data[CONF_NOTICE_ROUTE_MODE]]
        feed = await self.client.fetch_alert_feed(network)
        return build_notice_summary(feed, network, scope, value, dt_util.utcnow())

    async def _async_update_journey(self) -> JourneySummary:
        """Update journey planner data and live vehicle tracking."""
        plan_task = self.client.plan_journey(
            start_location_id=self.start_location_id,
            start_name=self.start_name,
            end_location_id=self.end_location_id,
            end_name=self.end_name,
            transport_modes=self.transport_modes,
            time_search_mode=self.time_search_mode,
            max_walking_distance=self.max_walking_distance,
            walking_speed=self.walking_speed,
        )

        fetch_realtime = self.realtime_region != REALTIME_REGION_NONE
        vehicle_task = (
            self.client.fetch_vehicle_positions(self.realtime_region)
            if fetch_realtime and self.track_vehicle
            else asyncio.sleep(0, result=())
        )
        trip_task = (
            self.client.fetch_trip_updates(self.realtime_region, preserve_stale=True)
            if fetch_realtime
            else asyncio.sleep(0, result={})
        )

        plan_res, vp_res, tu_res = await asyncio.gather(
            plan_task, vehicle_task, trip_task
        )

        if not isinstance(plan_res, JourneyPlanResult):
            plan_res = JourneyPlanResult()

        now = datetime.now(UTC)
        followed = self._followed_journey
        pinned = (
            followed if followed is not None and followed.has_departed(now) else None
        )
        timetables = await self._async_get_trip_timetables(
            plan_res, pinned.itinerary if pinned is not None else None
        )
        trip_updates = tu_res if isinstance(tu_res, dict) else {}
        feeds = ProgressFeeds(
            trip_updates=trip_updates,
            vehicle_positions=vp_res if isinstance(vp_res, (tuple, list)) else (),
            timetables=timetables,
            realtime_region=self.realtime_region,
            region_confirmed=self.region_confirmed,
        )
        planned_at = pinned.planned_at if pinned is not None else now
        itinerary = (
            pinned.itinerary
            if pinned is not None
            else snapshot_itinerary(plan_res.itineraries[0])
            if plan_res.itineraries
            else None
        )
        progress = evaluate_progress(
            itinerary,
            planned_at=planned_at,
            now=now,
            tracking_basis="pinned_itinerary" if pinned else "planner_first_itinerary",
            feeds=feeds,
            memory=followed.memory if followed is not None else None,
        )
        grace = timedelta(seconds=JOURNEY_PROGRESS_GRACE_SECONDS)
        if (
            pinned is not None
            and progress.progress.state != "cancelled"
            and progress.final_arrival is not None
            and now > progress.final_arrival + grace
        ):
            planned_at = now
            itinerary = (
                snapshot_itinerary(plan_res.itineraries[0])
                if plan_res.itineraries
                else None
            )
            progress = evaluate_progress(
                itinerary, planned_at=planned_at, now=now, feeds=feeds
            )
        summary = build_journey_summary(
            plan=plan_res,
            trip_timetables=timetables,
            vehicle_positions=vp_res,
            track_vehicle=self.track_vehicle,
            realtime_region=self.realtime_region,
            region_confirmed=self.region_confirmed,
            trip_updates=trip_updates,
            now=now,
            fare_preference=self.fare_preference,
            origin_name_fallback=self.start_name,
            destination_name_fallback=self.end_name,
        )

        summary.progress = progress.progress
        self._followed_journey = (
            _FollowedJourney(itinerary, planned_at, progress.memory)
            if itinerary is not None
            and itinerary.legs
            and progress.progress.state != "cancelled"
            and (
                progress.final_arrival is None or now <= progress.final_arrival + grace
            )
            else None
        )
        return summary

    async def _async_get_trip_timetables(
        self, plan: JourneyPlanResult, pinned: JourneyItinerary | None = None
    ) -> dict[str, TripTimetable]:
        """Cache bounded optional enrichment without affecting core availability."""
        now = time.monotonic()
        self._trip_cache = {
            key: value for key, value in self._trip_cache.items() if value[0] > now
        }
        current_legs = plan.itineraries[0].legs if plan.itineraries else []
        legs = [*(pinned.legs if pinned is not None else ()), *current_legs]
        ids = list(
            dict.fromkeys(
                leg.tripId
                for leg in legs
                if leg.tripId and leg.travelMode.lower() != "walk"
            )
        )[:TRIP_PAGE_MAX_PER_REFRESH]
        missing = [trip_id for trip_id in ids if trip_id not in self._trip_cache]
        results = await asyncio.gather(
            *(self.client.async_get_trip_timetable(trip_id) for trip_id in missing),
            return_exceptions=True,
        )
        for trip_id, result in zip(missing, results, strict=True):
            timetable = result if isinstance(result, TripTimetable) else None
            if isinstance(result, BaseException):
                _LOGGER.debug(
                    "Optional trip timetable unavailable (%s)", type(result).__name__
                )
            ttl = (
                TRIP_PAGE_SUCCESS_TTL
                if timetable is not None
                else TRIP_PAGE_NEGATIVE_TTL
            )
            self._trip_cache[trip_id] = (time.monotonic() + ttl, timetable)
        while len(self._trip_cache) > TRIP_PAGE_CACHE_LIMIT:
            self._trip_cache.pop(next(iter(self._trip_cache)))
        return {
            trip_id: cached[1]
            for trip_id in ids
            if (cached := self._trip_cache.get(trip_id)) is not None
            and cached[1] is not None
        }

    async def _async_update_stop(self) -> StopSummary:
        """Update departure board for a single stop/station."""
        stop_id = self.entry.data.get(CONF_STOP_LOCATION_ID, "")
        stop_name = self.entry.data.get(CONF_STOP_NAME, "")

        timetable = await self.client.fetch_stop_timetable(stop_id)
        departures, arrivals = _stop_board_rows(timetable, self.transport_modes)
        now = datetime.now(UTC)
        disruptions = stop_disruption_fields(
            timetable.serviceAlerts,
            self.data if isinstance(self.data, StopSummary) else None,
            now,
        )
        summary = StopSummary(
            stop_id=stop_id,
            stop_name=stop_name or timetable.name,
            departures=[row.model_dump() for row in departures],
            arrivals=[row.model_dump() for row in arrivals],
            last_updated=now,
            **disruptions,
        )
        for row in departures:
            if row.is_cancelled or row.is_skipped:
                continue
            scheduled = parse_iso_datetime(row.scheduled_departure_time)
            expected = parse_iso_datetime(row.expected_departure_time)
            effective = expected or scheduled
            if effective is None or effective < now:
                continue
            summary.next_departure_time = scheduled
            summary.next_route = row.route
            summary.next_vehicle = row.vehicle
            summary.next_platform = row.platform
            summary.next_headsign = row.headsign
            if expected is not None:
                summary.predicted_departure_time = expected
                summary.realtime_status = "live"
                if scheduled is not None:
                    delay_seconds = (expected - scheduled).total_seconds()
                    summary.departure_delay_seconds = round(delay_seconds)
                    summary.delay_mins = round(delay_seconds / 60)
                    summary.delay_source = "stop_event"
            break
        return summary

    async def async_shutdown(self) -> None:
        """Cleanly close coordinator connections."""
        await super().async_shutdown()
        await self.client.close()
