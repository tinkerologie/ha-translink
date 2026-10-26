"""Client module for the Translink integration."""

from .api.client import (
    TranslinkApiError,
    TranslinkClient,
    TranslinkConnectionError,
    TranslinkResponseError,
    build_journey_summary,
    calculate_plan_hash,
    parse_iso_datetime,
    redact_sensitive,
)
from .api.gtfs_realtime import (
    AlertRecord,
    StopTimeEventRecord,
    StopTimeUpdateRecord,
    TripUpdateRecord,
    VehiclePositionRecord,
    parse_alerts,
    parse_trip_updates,
    parse_vehicle_positions,
)
from .api.models import (
    CallingStop,
    CallingStopRealtime,
    JourneyPlanResult,
    JourneySummary,
    LocationSearchResult,
    StopSummary,
    TripDeparture,
    TripTimetable,
)
from .api.trip_page import TripPageParseError

__all__ = [
    "AlertRecord",
    "CallingStop",
    "CallingStopRealtime",
    "JourneyPlanResult",
    "JourneySummary",
    "LocationSearchResult",
    "StopSummary",
    "StopTimeEventRecord",
    "StopTimeUpdateRecord",
    "TranslinkApiError",
    "TranslinkClient",
    "TranslinkConnectionError",
    "TranslinkResponseError",
    "TripDeparture",
    "TripPageParseError",
    "TripTimetable",
    "TripUpdateRecord",
    "VehiclePositionRecord",
    "build_journey_summary",
    "calculate_plan_hash",
    "parse_alerts",
    "parse_iso_datetime",
    "parse_trip_updates",
    "parse_vehicle_positions",
    "redact_sensitive",
]
