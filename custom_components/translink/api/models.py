"""Pydantic v2 models for Translink Queensland payloads and summaries."""

from __future__ import annotations

from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type JourneyStatus = Literal[
    "scheduled",
    "on_time",
    "delayed",
    "departed",
    "arrived",
    "no_service",
]


class TranslinkApiModel(BaseModel):
    """Base model following Pydantic v2 conventions."""

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        populate_by_name=True,
        validate_default=True,
    )


class LocationSearchResult(TranslinkApiModel):
    """Result from /api/location/search."""

    LocationId: str
    Description: str

    @property
    def id(self) -> str:
        """Alias for LocationId."""
        return self.LocationId

    @property
    def name(self) -> str:
        """Alias for Description."""
        return self.Description


class Position(TranslinkApiModel):
    """Geographic position coordinates."""

    lat: float
    lng: float


class StationInfo(TranslinkApiModel):
    """Station info."""

    id: str | None = None
    name: str | None = None
    stopType: str | None = None
    position: Position | None = None


class StopInfo(TranslinkApiModel):
    """Stop/platform info."""

    id: str | None = None
    name: str | None = None
    platform: str | None = None
    zone: str | None = None
    stopType: str | None = None
    position: Position | None = None
    station: StationInfo | None = None


class RouteLine(TranslinkApiModel):
    """Route line representation."""

    id: str | None = None
    name: str | None = None
    code: str | None = None
    textColorCode: str | None = None
    hexColorCode: str | None = None


class LegRoute(TranslinkApiModel):
    """Public transport route details."""

    id: str | None = None
    regionId: str | None = None
    regionName: str | None = None
    vehicle: str | None = None
    code: str | None = None
    direction: str | None = None
    isExpress: bool = False
    isFree: bool = False
    isPrepaid: bool = False
    isTransLinkService: bool = True
    isSchool: bool = False
    name: str | None = None
    headsign: str | None = None
    headsignShort: str | None = None
    operator: str | None = None
    hexColorCode: str | None = None
    textColorCode: str | None = None
    lines: list[RouteLine] = Field(default_factory=list)


class FareItem(TranslinkApiModel):
    """Fare details."""

    type: str
    name: str
    price: float = 0.0


class NoticeItem(TranslinkApiModel):
    """Notice or alert details."""

    id: int | str | None = None
    severity: str | None = None


class SkippedStop(TranslinkApiModel):
    """Intermediate / skipped stop."""

    id: str | None = None
    name: str | None = None


class JourneyLeg(TranslinkApiModel):
    """Single leg of a journey."""

    arrivalTimeUtc: str | None = None
    departureTimeUtc: str | None = None
    distanceM: int = 0
    durationMins: int = 0
    origin: StopInfo | None = None
    destination: StopInfo | None = None
    legRoute: LegRoute | None = None
    travelMode: str = "Walk"
    tripId: str | None = None
    tripHeadsign: str | None = None
    numberOfStops: int = 0
    skippedStops: list[SkippedStop] = Field(default_factory=list)
    sameVehicleContinuation: bool = False
    polyline: str | None = None
    maxNoticeSeverity: str | None = None
    notices: list[NoticeItem] = Field(default_factory=list)


class JourneyItinerary(TranslinkApiModel):
    """Single complete journey itinerary."""

    durationMins: int = 0
    endTimeUtc: str | None = None
    firstDepartureTimeUtc: str | None = None
    lastArrivalTimeUtc: str | None = None
    fares: list[FareItem] = Field(default_factory=list)
    legs: list[JourneyLeg] = Field(default_factory=list)


class PlanNotice(TranslinkApiModel):
    """Notice or disruption details from Journey Planner."""

    id: int | str | None = None
    title: str | None = None
    description: str | None = None
    cause: str | None = None
    effect: str | None = None
    startsUtc: str | None = None
    endsUtc: str | None = None


class JourneyPlanResult(TranslinkApiModel):
    """Response from /api/plan."""

    itineraries: list[JourneyItinerary] = Field(default_factory=list)
    notices: list[PlanNotice] = Field(default_factory=list)


class JourneySummary(TranslinkApiModel):
    """Normalized, typed presentation summary for Home Assistant entities."""

    status: JourneyStatus = "scheduled"
    departure_time: datetime | None = None
    arrival_time: datetime | None = None
    duration_mins: int = 0
    transfers: int = 0
    next_service_name: str | None = None
    next_service_vehicle: str | None = None
    next_service_headsign: str | None = None
    next_service_route_code: str | None = None
    next_service_color: str | None = None
    operator: str | None = None
    origin_name: str = ""
    origin_platform: str | None = None
    destination_name: str = ""
    destination_platform: str | None = None
    fare_price: float | None = None
    fare_currency: str = "AUD"
    fare_type: str | None = None
    fares_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    walking_distance_m: int = 0
    delay_mins: int = 0
    disruptions_count: int = 0
    disruptions: list[dict[str, Any]] = Field(default_factory=list)
    disruptions_description: str = "No active disruptions"
    disruptions_summary: str = "Normal"
    latest_disruption_title: str | None = None
    latest_disruption_description: str | None = None
    trip_id: str | None = None
    vehicle_id: str | None = None
    vehicle_label: str | None = None
    vehicle_latitude: float | None = None
    vehicle_longitude: float | None = None
    vehicle_bearing: float | None = None
    vehicle_speed: float | None = None
    vehicle_tracked: bool = False
    polyline: str | None = None
    itinerary_legs: list[dict[str, Any]] = Field(default_factory=list)
    last_updated: datetime | None = None


class StopDepartureItem(TranslinkApiModel):
    """Single departure item from a stop."""

    route_code: str
    route_name: str
    vehicle: str
    headsign: str
    departure_time: datetime | None = None
    platform: str | None = None
    delay_mins: int = 0
    trip_id: str | None = None


class StopSummary(TranslinkApiModel):
    """Normalized presentation summary for stop departure boards."""

    stop_id: str
    stop_name: str
    stop_type: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    next_departure_time: datetime | None = None
    next_route: str | None = None
    next_vehicle: str | None = None
    next_platform: str | None = None
    next_headsign: str | None = None
    delay_mins: int = 0
    departures: list[dict[str, Any]] = Field(default_factory=list)
    disruptions_count: int = 0
    disruptions: list[dict[str, Any]] = Field(default_factory=list)
    disruptions_description: str = "No active disruptions"
    disruptions_summary: str = "Normal"
    latest_disruption_title: str | None = None
    latest_disruption_description: str | None = None
    last_updated: datetime | None = None


class TripDeparture(TranslinkApiModel):
    """An actual scheduled stop visit supplied by the public trip page."""

    stopId: str
    name: str | None = None
    order: int
    scheduledDepartureUtc: str
    canBoardDebark: str | None = None

    @field_validator("scheduledDepartureUtc")
    @classmethod
    def validate_utc_time(cls, value: str) -> str:
        """Reject missing time zones and non-UTC timetable values."""
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError("Scheduled departure must be timezone-aware UTC")
        return value


class TripTimetable(TranslinkApiModel):
    """Validated scheduled calls for one exact planner trip."""

    id: str
    headsign: str | None = None
    departures: list[TripDeparture]

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        """A list preserves occurrences, so ambiguous or reversed order is invalid."""
        orders = [stop.order for stop in self.departures]
        if any(a >= b for a, b in pairwise(orders)):
            raise ValueError("Stop orders must be unique and increasing")
        return self


class CallingStopRealtime(TranslinkApiModel):
    """Explicit GTFS-RT values, separate from scheduled timetable information."""

    sequence: int | None = None
    scheduleRelationship: Literal["scheduled", "skipped", "no_data", "unknown"] = (
        "unknown"
    )
    arrivalTimeUtc: str | None = None
    arrivalDelaySeconds: int | None = None
    arrivalUncertaintySeconds: int | None = None
    departureTimeUtc: str | None = None
    departureDelaySeconds: int | None = None
    departureUncertaintySeconds: int | None = None


class CallingStop(TranslinkApiModel):
    """Additive per-leg calling-stop contract with explicit schedule provenance."""

    order: int | None = None
    stopId: str | None
    name: str | None = None
    platform: str | None = None
    role: Literal["origin", "intermediate", "destination"]
    canBoardDebark: str | None = None
    scheduledTimeUtc: str | None = None
    realtime: CallingStopRealtime | None = None
