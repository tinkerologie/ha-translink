"""Data update coordinator for the Translink integration."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    JourneyPlanResult,
    JourneySummary,
    StopSummary,
    TranslinkApiError,
    TranslinkClient,
    TripTimetable,
    build_journey_summary,
)
from .const import (
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
            raise UpdateFailed(f"Translink update failed: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching Translink data")
            raise UpdateFailed(
                f"Unexpected error fetching Translink data: {err}"
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

        # Select reference destination avoiding collision if stop is Central
        ref_id = "ST:place_censta"
        ref_name = "Central Station"
        if stop_id == "ST:place_censta" or "central" in stop_name.lower():
            ref_id = "ST:place_romsta"
            ref_name = "Roma Street Station"

        plan = await self.client.plan_journey(
            start_location_id=stop_id,
            start_name=stop_name,
            end_location_id=ref_id,
            end_name=ref_name,
            transport_modes=self.transport_modes,
            time_search_mode="LeaveAfter",
            max_walking_distance=self.max_walking_distance,
        )

        tu_res = await self.client.fetch_trip_updates()

        journey_summary = build_journey_summary(
            plan=plan,
            trip_updates=tu_res,
            origin_name_fallback=stop_name,
            destination_name_fallback=ref_name,
        )

        # Collect upcoming departures from across planned itineraries
        departures: list[dict[str, Any]] = []
        for itin in plan.itineraries:
            for leg in itin.legs:
                if leg.travelMode.lower() != "walk":
                    departures.append(
                        {
                            "route": (leg.legRoute.name if leg.legRoute else None)
                            or leg.tripHeadsign
                            or "Transit",
                            "vehicle": leg.travelMode,
                            "headsign": leg.tripHeadsign,
                            "departure_time": leg.departureTimeUtc,
                            "platform": leg.origin.platform if leg.origin else None,
                        }
                    )
                    break
        if not departures:
            departures = journey_summary.itinerary_legs

        stop_summary = StopSummary(
            stop_id=stop_id,
            stop_name=stop_name,
            next_departure_time=journey_summary.departure_time,
            next_route=journey_summary.next_service_name,
            next_vehicle=journey_summary.next_service_vehicle,
            next_platform=journey_summary.origin_platform,
            next_headsign=journey_summary.next_service_headsign,
            delay_mins=journey_summary.delay_mins,
            departures=departures,
            disruptions_count=journey_summary.disruptions_count,
            disruptions=journey_summary.disruptions,
            disruptions_description=journey_summary.disruptions_description,
            disruptions_summary=journey_summary.disruptions_summary,
            latest_disruption_title=journey_summary.latest_disruption_title,
            latest_disruption_description=journey_summary.latest_disruption_description,
            last_updated=journey_summary.last_updated,
        )

        return stop_summary

    async def async_shutdown(self) -> None:
        """Cleanly close coordinator connections."""
        await super().async_shutdown()
        await self.client.close()
