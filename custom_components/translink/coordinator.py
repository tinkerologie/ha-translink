"""Data update coordinator for the Translink integration."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import stop_disruption_fields
from .api.models import (
    StopDepartureItem,
    StopDeparturePlatformChange,
    StopTimetable,
    TimetableDeparture,
    TimetableRoute,
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
    MIN_SCAN_INTERVAL,
    MODE_JOURNEY,
    TRIP_PAGE_CACHE_LIMIT,
    TRIP_PAGE_MAX_PER_REFRESH,
    TRIP_PAGE_NEGATIVE_TTL,
    TRIP_PAGE_SUCCESS_TTL,
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


def _departure_row(
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


def _stop_departure_rows(
    timetable: StopTimetable, modes: list[str]
) -> list[StopDepartureItem]:
    """Select boardable visits and deduplicate only complete visit identities."""
    routes_by_id: dict[str, list[TimetableRoute]] = defaultdict(list)
    for route in timetable.routes:
        routes_by_id[route.id].append(route)

    visits: dict[str, tuple[TimetableDeparture, list[TimetableRoute], str | None]] = {}
    for index, departure in enumerate(timetable.departures):
        if departure.canBoardDebark == "Alighting":
            continue
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
        previous = visits.get(visit_id)
        if previous is None or (
            previous[0].realtime is None and departure.realtime is not None
        ):
            visits[visit_id] = departure, routes, vehicle

    ordered = sorted(
        visits.items(),
        key=lambda item: (
            parse_iso_datetime(item[1][0].scheduledDepartureUtc)
            or datetime.max.replace(tzinfo=UTC)
        ),
    )
    return [
        _departure_row(departure, routes, vehicle, visit_id)
        for visit_id, (departure, routes, vehicle) in ordered
    ]


class TranslinkCoordinator(DataUpdateCoordinator[JourneySummary | StopSummary]):
    """Coordinator to fetch and update data from Translink Queensland."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.mode = entry.data.get(CONF_MODE, DEFAULT_MODE)

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

    async def _async_update_data(self) -> JourneySummary | StopSummary:
        """Fetch updated data from Translink."""
        try:
            if self.mode == MODE_JOURNEY:
                return await self._async_update_journey()
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

        vehicle_task = (
            self.client.fetch_vehicle_positions()
            if self.track_vehicle
            else asyncio.sleep(0, result={})
        )
        trip_task = self.client.fetch_trip_updates()

        plan_res, vp_res, tu_res = await asyncio.gather(
            plan_task, vehicle_task, trip_task
        )

        if not isinstance(plan_res, JourneyPlanResult):
            plan_res = JourneyPlanResult()

        timetables = await self._async_get_trip_timetables(plan_res)
        summary = build_journey_summary(
            plan=plan_res,
            trip_timetables=timetables,
            vehicle_positions=vp_res if isinstance(vp_res, dict) else {},
            trip_updates=tu_res if isinstance(tu_res, dict) else {},
            fare_preference=self.fare_preference,
            origin_name_fallback=self.start_name,
            destination_name_fallback=self.end_name,
        )

        return summary

    async def _async_get_trip_timetables(
        self, plan: JourneyPlanResult
    ) -> dict[str, TripTimetable]:
        """Cache bounded optional enrichment without affecting core availability."""
        now = time.monotonic()
        self._trip_cache = {
            key: value for key, value in self._trip_cache.items() if value[0] > now
        }
        legs = plan.itineraries[0].legs if plan.itineraries else []
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
        rows = _stop_departure_rows(timetable, self.transport_modes)
        now = datetime.now(UTC)
        disruptions = stop_disruption_fields(
            timetable.serviceAlerts,
            self.data if isinstance(self.data, StopSummary) else None,
            now,
        )
        summary = StopSummary(
            stop_id=stop_id,
            stop_name=stop_name or timetable.name,
            departures=[row.model_dump() for row in rows],
            last_updated=now,
            **disruptions,
        )
        for row in rows:
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
