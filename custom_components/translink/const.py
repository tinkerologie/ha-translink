"""Constants for the Translink Queensland integration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

DOMAIN: Final = "translink"
CARD_FILENAME: Final = "translink-cards.js"
CARD_URL: Final = f"/translink_cards/{CARD_FILENAME}"

# Configuration keys
CONF_MODE: Final = "mode"
MODE_JOURNEY: Final = "journey"
MODE_STOP: Final = "stop"
MODE_NOTICES: Final = "notices"

DEVICE_MODELS: Final = {
    MODE_JOURNEY: "Public Transport Journey",
    MODE_STOP: "Station Departure Board",
    MODE_NOTICES: "Service Notices",
}

CONF_NOTICE_NETWORK: Final = "notice_network"
CONF_NOTICE_SCOPE: Final = "notice_scope"
CONF_NOTICE_ROUTE_ID: Final = "notice_route_id"
CONF_NOTICE_ROUTE_MODE: Final = "notice_route_mode"
SETUP_NEARBY_STOP: Final = "nearby_stop"

CONF_NAME: Final = "name"
CONF_START_LOCATION_ID: Final = "start_location_id"
CONF_START_NAME: Final = "start_name"
CONF_END_LOCATION_ID: Final = "end_location_id"
CONF_END_NAME: Final = "end_name"
CONF_STOP_LOCATION_ID: Final = "stop_location_id"
CONF_STOP_NAME: Final = "stop_name"

CONF_TRANSPORT_MODES: Final = "transport_modes"
CONF_TIME_SEARCH_MODE: Final = "time_search_mode"
CONF_MAX_WALKING_DISTANCE: Final = "max_walking_distance"
CONF_WALKING_SPEED: Final = "walking_speed"
CONF_FARE_PREFERENCE: Final = "fare_preference"
CONF_TRACK_VEHICLE: Final = "track_vehicle"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_REALTIME_REGION: Final = "realtime_region"

# Defaults
DEFAULT_MODE: Final = MODE_JOURNEY
DEFAULT_TRANSPORT_MODES: Final = ["Bus", "Ferry", "Train", "Tram"]
DEFAULT_TIME_SEARCH_MODE: Final = "LeaveAfter"
DEFAULT_WALKING_SPEED: Final = "Normal"
DEFAULT_MAX_WALKING_DISTANCE: Final = 4000
DEFAULT_FARE_PREFERENCE: Final = "Adult"
DEFAULT_TRACK_VEHICLE: Final = True
DEFAULT_SCAN_INTERVAL: Final = 60  # seconds
MIN_SCAN_INTERVAL: Final = 30  # seconds

# On-demand journey planner response bounds
DEFAULT_ALTERNATIVES_LIMIT: Final = 5
MAX_ALTERNATIVES_LIMIT: Final = 10
MAX_ALTERNATIVE_LEGS: Final = 20
MAX_ALTERNATIVE_NOTICES: Final = 10
JOURNEY_SORT_OPTIONS: Final = ("departure", "arrival", "duration")

# Options lists
AVAILABLE_MODES: Final = [MODE_JOURNEY, MODE_STOP]
AVAILABLE_TRANSPORT_MODES: Final = ["Bus", "Ferry", "Train", "Tram"]
AVAILABLE_TIME_SEARCH_MODES: Final = ["LeaveAfter", "ArriveBefore"]
AVAILABLE_WALKING_SPEEDS: Final = ["Slow", "Normal", "Fast"]
AVAILABLE_FARE_PREFERENCES: Final = ["Adult", "Concession"]

# Service & API Base URLs
JP_API_BASE_URL: Final = "https://jp.translink.com.au"
GTFSRT_API_BASE_URL: Final = "https://gtfsrt.api.translink.com.au"

LOCATION_STATION_PREFIX: Final = "ST:"
LOCATION_STOP_PREFIX: Final = "SI:"
LOCATION_PLACE_PREFIX: Final = "PL:"

ENDPOINT_LOCATION_SEARCH: Final = "/api/location/search"
ENDPOINT_PLAN: Final = "/api/plan"
ENDPOINT_STOP_BY_GEOLOCATION: Final = "/api/stop/bygeolocation"
NEARBY_RESULT_LIMIT: Final = 10
ENDPOINT_STOP_TIMETABLE: Final = "/api/stop/timetable/"
STOP_TIMETABLE_MAX_BYTES: Final = 1024 * 1024

GTFS_FEED_VEHICLE_POSITIONS: Final = "/api/realtime/SEQ/VehiclePositions"
GTFS_FEED_TRIP_UPDATES: Final = "/api/realtime/SEQ/TripUpdates"
GTFS_FEED_ALERTS: Final = "/api/realtime/SEQ/Alerts"

REALTIME_REGION_SEQ: Final = "SEQ"
REALTIME_REGION_CAIRNS: Final = "CNS"
REALTIME_REGION_NONE: Final = "none"
DEFAULT_REALTIME_REGION: Final = REALTIME_REGION_SEQ


@dataclass(frozen=True, slots=True)
class RealtimeFeedRegion:
    """Published feed paths and their planner region identifiers."""

    trip_updates: str
    vehicle_positions: str
    alerts: str
    planner_region_id: str
    planner_region_name: str
    strict_identity: bool = False


REALTIME_FEED_REGIONS: Final = {
    REALTIME_REGION_SEQ: RealtimeFeedRegion(
        GTFS_FEED_TRIP_UPDATES,
        GTFS_FEED_VEHICLE_POSITIONS,
        GTFS_FEED_ALERTS,
        planner_region_id="T",
        planner_region_name="SEQ",
    ),
    REALTIME_REGION_CAIRNS: RealtimeFeedRegion(
        "/api/realtime/CNS/TripUpdates",
        "/api/realtime/CNS/VehiclePositions",
        "/api/realtime/CNS/Alerts",
        planner_region_id="C",
        planner_region_name="Cairns",
        strict_identity=True,
    ),
}

ALERT_NETWORK_NAMES: Final = {
    REALTIME_REGION_SEQ: "South East Queensland",
    REALTIME_REGION_CAIRNS: "Cairns",
}
ALERT_FEED_MAX_BYTES: Final = 2 * 1024 * 1024
ALERT_FEED_TIMEOUT: Final = 10

NOTICE_ROUTE_TYPES: Final = {"Bus": 3, "Ferry": 4, "Train": 2, "Tram": 0}
NOTICE_LIMIT: Final = 20
NOTICE_DESCRIPTION_LIMIT: Final = 1024
NOTICE_SELECTOR_LIMIT: Final = 10
NOTICE_PERIOD_LIMIT: Final = 10
NOTICE_ROUTE_ID_LIMIT: Final = 128

REALTIME_MAX_AGE_SECONDS: Final = 300
REALTIME_MAX_FUTURE_SKEW_SECONDS: Final = 60

TIMEZONE_BRISBANE: Final = "Australia/Brisbane"
BRISBANE_TZ: Final = TIMEZONE_BRISBANE

# Default intervals
STORAGE_VERSION: Final = 1

# Transport mode icon mappings
VEHICLE_ICON_MAP: Final[dict[str, str]] = {
    "train": "mdi:train",
    "bus": "mdi:bus",
    "ferry": "mdi:ferry",
    "boat": "mdi:ferry",
    "tram": "mdi:tram",
    "light rail": "mdi:tram",
}


def resolve_realtime_region(data: Mapping[str, object]) -> tuple[str, bool]:
    """Resolve the journey feed and whether the user explicitly selected it."""
    if data.get(CONF_MODE, DEFAULT_MODE) != MODE_JOURNEY:
        return REALTIME_REGION_NONE, False
    if CONF_REALTIME_REGION not in data:
        return DEFAULT_REALTIME_REGION, False
    region = data[CONF_REALTIME_REGION]
    if isinstance(region, str) and (
        region in REALTIME_FEED_REGIONS or region == REALTIME_REGION_NONE
    ):
        return region, True
    return REALTIME_REGION_NONE, False


def get_vehicle_icon(vehicle: str | None, default: str = "mdi:train-bus") -> str:
    """Resolve transport mode icon from vehicle string."""
    if vehicle:
        v_lower = vehicle.lower()
        for mode, icon in VEHICLE_ICON_MAP.items():
            if mode in v_lower:
                return icon
    return default


# Chosen request/cache bounds with headroom; these are not upstream service limits.
ENDPOINT_TRIP_PAGE: Final = "/plan-your-journey/timetables/trip/"
PUBLIC_TRIP_TIMETABLE_BASE_URL: Final = f"{JP_API_BASE_URL}{ENDPOINT_TRIP_PAGE}"
TRIP_PAGE_TIMEOUT: Final = 10
TRIP_PAGE_MAX_BYTES: Final = 1024 * 1024
TRIP_PAGE_CONCURRENCY: Final = 2
TRIP_PAGE_MAX_PER_REFRESH: Final = 4
TRIP_PAGE_SUCCESS_TTL: Final = 30 * 60
TRIP_PAGE_NEGATIVE_TTL: Final = 5 * 60
TRIP_PAGE_CACHE_LIMIT: Final = 32
