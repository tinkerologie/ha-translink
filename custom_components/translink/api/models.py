"""Pydantic v2 models for Translink Queensland payloads and summaries."""

from __future__ import annotations

from datetime import datetime, timedelta
from itertools import pairwise
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    OnErrorOmit,
    StrictBool,
    ValidationError,
    field_validator,
    model_validator,
)

from ..const import LOCATION_PLACE_PREFIX, LOCATION_STATION_PREFIX, LOCATION_STOP_PREFIX

type JourneyStatus = Literal[
    "scheduled",
    "on_time",
    "early",
    "delayed",
    "cancelled",
    "boarding_skipped",
    "departed",
    "arrived",
    "no_service",
]

type RealtimeStatus = Literal[
    "live", "unavailable", "stale", "no_prediction", "no_data"
]
type DelaySource = Literal["stop_event", "trip"]
type StopRelationship = Literal["scheduled", "skipped", "no_data", "unknown"]


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

    @property
    def kind(self) -> Literal["station", "stop", "place", "unknown"]:
        """Classify the public location ID by its prefix."""
        if self.id.startswith(LOCATION_STATION_PREFIX):
            return "station"
        if self.id.startswith(LOCATION_STOP_PREFIX):
            return "stop"
        if self.id.startswith(LOCATION_PLACE_PREFIX):
            return "place"
        return "unknown"

    @property
    def is_board_candidate(self) -> bool:
        """Return whether this location can be used for a departure board."""
        return self.kind in ("station", "stop")


class NearbyStation(TranslinkApiModel):
    """Station identity attached to a nearby platform."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class NearbyStop(TranslinkApiModel):
    """Nearby stop metadata, without its geographic position."""

    model_config = ConfigDict(str_strip_whitespace=False)

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    distanceM: float = Field(strict=True, ge=0, allow_inf_nan=False)
    stopId: str | None = None
    stopType: str | None = None
    station: NearbyStation | None = None


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


def _require_utc_time(value: str) -> str:
    """Keep the original timestamp after verifying its UTC offset."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("Timetable departure must be timezone-aware UTC")
    return value


type TimetableTime = Annotated[str, AfterValidator(_require_utc_time)]


class TimetableRouteLine(TranslinkApiModel):
    """Mode metadata for one line of a timetable route."""

    vehicleType: str | None = None


class TimetableRoute(TranslinkApiModel):
    """Timetable route metadata, which may repeat across directions."""

    id: str
    shortName: str | None = None
    code: str | None = None
    name: str | None = None
    direction: str | None = None
    routeHexColor: str | None = None
    lines: list[OnErrorOmit[TimetableRouteLine]] | None = None


class TimetablePlatformChange(TranslinkApiModel):
    """Upstream platform-change metadata for a stop visit."""

    platform: str | None = None
    oldPlatform: str | None = None
    isSource: StrictBool | None = None


class TimetableRealtime(TranslinkApiModel):
    """Live data supplied for one stop visit."""

    expectedDepartureUtc: TimetableTime | None = None
    isExtra: StrictBool | None = None
    isSkipped: StrictBool | None = None
    isCancelled: StrictBool | None = None
    platformChange: TimetablePlatformChange | None = None


class TimetableDeparture(TranslinkApiModel):
    """One visit in a selected station or platform timetable."""

    id: str | None = None
    routeId: str | None = None
    headsign: str | None = None
    direction: str | None = None
    scheduledDepartureUtc: TimetableTime | None = None
    departurePlatform: str | None = None
    canBoardDebark: str | None = None
    realtime: TimetableRealtime | None = None

    @model_validator(mode="after")
    def validate_visit(self) -> Self:
        """Reject empty or unrelated records without requiring a complete identity."""
        if not (self.id or self.routeId or self.scheduledDepartureUtc):
            raise ValueError("Expected a timetable visit")
        return self


class TimetableNotice(PlanNotice):
    """A timetable notice with severity supplied alongside its details."""

    severity: str | None = None


class TimetableServiceAlerts(TranslinkApiModel):
    """Notices currently active at the selected location."""

    current: list[TimetableNotice]


class StopTimetable(TranslinkApiModel):
    """Public timetable and notices scoped to the requested station or platform."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    stops: list[StopInfo] | None = None
    station: StationInfo | None = None
    routes: list[OnErrorOmit[TimetableRoute]] = Field(default_factory=list)
    departures: list[OnErrorOmit[TimetableDeparture]]
    serviceAlerts: TimetableServiceAlerts | None = None

    @field_validator("serviceAlerts", mode="before")
    @classmethod
    def allow_unavailable_alerts(cls, value: Any) -> TimetableServiceAlerts | None:
        """A missing or unusable section carries no notice update."""
        if value is not None:
            try:
                return TimetableServiceAlerts.model_validate(value)
            except ValidationError:
                pass
        return None


class JourneyPlanResult(TranslinkApiModel):
    """Response from /api/plan."""

    itineraries: list[JourneyItinerary] = Field(default_factory=list)
    notices: list[PlanNotice] = Field(default_factory=list)


VehiclePositionStatus = Literal[
    "live", "stale", "ambiguous", "no_position", "no_active_leg", "disabled"
]


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
    delay_mins: int | None = None
    departure_delay_seconds: int | None = None
    arrival_delay_seconds: int | None = None
    predicted_departure_time: datetime | None = None
    predicted_arrival_time: datetime | None = None
    realtime_status: RealtimeStatus = "unavailable"
    realtime_updated_at: datetime | None = None
    delay_source: DelaySource | None = None
    boarding_relationship: StopRelationship | None = None
    alighting_skipped: bool = False
    disruptions_count: int = 0
    disruptions: list[dict[str, Any]] = Field(default_factory=list)
    disruptions_description: str = "No active disruptions"
    disruptions_summary: str = "Normal"
    latest_disruption_title: str | None = None
    latest_disruption_description: str | None = None
    trip_id: str | None = None
    active_leg_index: int | None = None
    active_trip_id: str | None = None
    active_route_name: str | None = None
    active_route_code: str | None = None
    active_route_color: str | None = None
    active_vehicle_type: str | None = None
    vehicle_position_status: VehiclePositionStatus = "no_active_leg"
    vehicle_position_timestamp: str | None = None
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


class StopDeparturePlatformChange(TranslinkApiModel):
    """Platform-change provenance exposed on a departure row."""

    platform: str | None
    old_platform: str | None
    is_source: bool | None


class StopDepartureItem(TranslinkApiModel):
    """Normalized stop timetable visit exposed on the Home Assistant board."""

    route: str
    vehicle: str | None
    headsign: str | None
    departure_time: str | None
    platform: str | None
    trip_id: str | None
    visit_id: str
    route_id: str | None
    direction: str | None
    boarding: str | None
    scheduled_departure_time: str | None
    expected_departure_time: str | None
    time_source: Literal["scheduled", "realtime"]
    is_cancelled: bool | None
    is_skipped: bool | None
    is_extra: bool | None
    platform_change: StopDeparturePlatformChange | None
    route_color: str | None


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
    delay_mins: int | None = None
    departure_delay_seconds: int | None = None
    arrival_delay_seconds: int | None = None
    predicted_departure_time: datetime | None = None
    realtime_status: RealtimeStatus = "unavailable"
    realtime_updated_at: datetime | None = None
    delay_source: DelaySource | None = None
    departures: list[dict[str, Any]] = Field(default_factory=list)
    arrivals: list[dict[str, Any]] = Field(default_factory=list)
    disruptions_count: int = 0
    disruptions: list[dict[str, Any]] = Field(default_factory=list)
    disruptions_description: str = "No active disruptions"
    disruptions_summary: str = "Normal"
    latest_disruption_title: str | None = None
    latest_disruption_description: str | None = None
    last_updated: datetime | None = None


class NoticeSummary(TranslinkApiModel):
    """Bounded regional service notices from one successful feed fetch."""

    network: str
    scope_type: Literal["network", "route", "mode"]
    scope_value: str | int | None
    feed_timestamp: datetime | None
    last_successful_fetch: datetime
    last_updated: datetime
    total_count: int
    shown_count: int
    active_count: int
    upcoming_count: int
    unclassified_count: int
    duplicates_dropped: int
    disruptions_count: int
    disruptions: list[dict[str, Any]]
    disruptions_description: str
    disruptions_summary: str
    latest_disruption_title: str | None
    latest_disruption_description: str | None


class TripDeparture(TranslinkApiModel):
    """An actual scheduled stop visit supplied by the public trip page."""

    stopId: str
    name: str | None = None
    order: int
    scheduledDepartureUtc: TimetableTime
    canBoardDebark: str | None = None


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
    scheduleRelationship: StopRelationship = "unknown"
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
