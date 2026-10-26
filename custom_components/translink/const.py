"""Constants for the Translink Queensland integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "translink"
CARD_FILENAME: Final = "translink-cards.js"
CARD_URL: Final = f"/translink_cards/{CARD_FILENAME}"

# Configuration keys
CONF_MODE: Final = "mode"
MODE_JOURNEY: Final = "journey"
MODE_STOP: Final = "stop"

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

# Options lists
AVAILABLE_MODES: Final = [MODE_JOURNEY, MODE_STOP]
AVAILABLE_TRANSPORT_MODES: Final = ["Bus", "Ferry", "Train", "Tram"]
AVAILABLE_TIME_SEARCH_MODES: Final = ["LeaveAfter", "ArriveBefore"]
AVAILABLE_WALKING_SPEEDS: Final = ["Slow", "Normal", "Fast"]
AVAILABLE_FARE_PREFERENCES: Final = ["Adult", "Concession"]

# Service & API Base URLs
JP_API_BASE_URL: Final = "https://jp.translink.com.au"
GTFSRT_API_BASE_URL: Final = "https://gtfsrt.api.translink.com.au"

ENDPOINT_LOCATION_SEARCH: Final = "/api/location/search"
ENDPOINT_PLAN: Final = "/api/plan"
ENDPOINT_STOP_BY_GEOLOCATION: Final = "/api/stop/bygeolocation"

GTFS_FEED_VEHICLE_POSITIONS: Final = "/api/realtime/SEQ/VehiclePositions"
GTFS_FEED_TRIP_UPDATES: Final = "/api/realtime/SEQ/TripUpdates"
GTFS_FEED_ALERTS: Final = "/api/realtime/SEQ/Alerts"

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
TRIP_PAGE_TIMEOUT: Final = 10
TRIP_PAGE_MAX_BYTES: Final = 1024 * 1024
TRIP_PAGE_CONCURRENCY: Final = 2
TRIP_PAGE_MAX_PER_REFRESH: Final = 4
TRIP_PAGE_SUCCESS_TTL: Final = 30 * 60
TRIP_PAGE_NEGATIVE_TTL: Final = 5 * 60
TRIP_PAGE_CACHE_LIMIT: Final = 32
