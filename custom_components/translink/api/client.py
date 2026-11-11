"""API client and data processing helpers for Translink Queensland."""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, TypedDict, TypeVar
from zoneinfo import ZoneInfo

import aiohttp
from pydantic import ValidationError
from yarl import URL

from ..const import (
    BRISBANE_TZ,
    DEFAULT_REALTIME_REGION,
    ENDPOINT_LOCATION_SEARCH,
    ENDPOINT_PLAN,
    ENDPOINT_STOP_BY_GEOLOCATION,
    ENDPOINT_STOP_TIMETABLE,
    ENDPOINT_TRIP_PAGE,
    GTFSRT_API_BASE_URL,
    JP_API_BASE_URL,
    MAX_ALTERNATIVE_LEGS,
    MAX_ALTERNATIVE_NOTICES,
    MAX_ALTERNATIVES_LIMIT,
    REALTIME_FEED_REGIONS,
    REALTIME_MAX_AGE_SECONDS,
    REALTIME_MAX_FUTURE_SKEW_SECONDS,
    STOP_TIMETABLE_MAX_BYTES,
    TRIP_PAGE_CONCURRENCY,
    TRIP_PAGE_MAX_BYTES,
    TRIP_PAGE_TIMEOUT,
    RealtimeFeedRegion,
)
from .gtfs_realtime import (
    STOP_NO_DATA,
    STOP_SKIPPED,
    TRIP_CANCELED,
    TRIP_DELETED,
    AlertRecord,
    StopTimeUpdateRecord,
    TripUpdateRecord,
    VehiclePositionRecord,
    extract_base_trip_id,
    parse_alerts,
    parse_feed_timestamp,
    parse_trip_updates,
    parse_vehicle_position_records,
)
from .models import (
    CallingStop,
    CallingStopRealtime,
    DelaySource,
    JourneyItinerary,
    JourneyLeg,
    JourneyPlanResult,
    JourneyStatus,
    JourneySummary,
    LocationSearchResult,
    PlanNotice,
    RealtimeStatus,
    StopRelationship,
    StopSummary,
    StopTimetable,
    TimetableServiceAlerts,
    TripTimetable,
    VehiclePositionStatus,
)

_LOGGER = logging.getLogger(__name__)
_FeedRecords = TypeVar("_FeedRecords")

USER_AGENT = "HomeAssistant-Translink/2026.10.0"
DELAYED_THRESHOLD_MINUTES = 3
EARLY_THRESHOLD_MINUTES = -1
VEHICLE_POSITION_MAX_AGE_SECONDS: Final = 90
VEHICLE_POSITION_MAX_FUTURE_SKEW_SECONDS: Final = 30


class TranslinkApiError(Exception):
    """Base exception for Translink API failures."""


class TranslinkConnectionError(TranslinkApiError):
    """Raised when connection to Translink fails."""


class TranslinkResponseError(TranslinkApiError):
    """Raised when Translink returns an error status code."""


def calculate_plan_hash(query_string: str) -> int:
    """Calculate 32-bit signed hash matching Translink's frontend hash function."""
    h = 0
    for ch in query_string:
        h = ((h << 5) - h + ord(ch)) & 0xFFFFFFFF
        if h >= 0x80000000:
            h -= 0x100000000
    return h


@dataclass(frozen=True)
class JourneyPlanRequest:
    """Encoded request sent to the public journey planner."""

    url: str
    body: str
    request_id: int
    headers: dict[str, str]


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Safely parse an ISO-8601 UTC timestamp string."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(UTC)
    except (ValueError, TypeError):
        return None


SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "latitude",
        "longitude",
        "origin_latitude",
        "origin_longitude",
        "destination_latitude",
        "destination_longitude",
        "vehicle_latitude",
        "vehicle_longitude",
        "lat",
        "lng",
        "api_key",
        "token",
        "password",
        "secret",
    }
)


def redact_sensitive(data: Any) -> Any:
    """Recursively redact sensitive data for diagnostics."""
    if isinstance(data, dict):
        return {
            k: "**REDACTED**"
            if str(k).lower() in SENSITIVE_KEYS
            else redact_sensitive(v)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [redact_sensitive(item) for item in data]
    return data


class TranslinkClient:
    """Asynchronous client for Translink Queensland APIs and GTFS Realtime feeds."""

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        jp_base_url: str = JP_API_BASE_URL,
        gtfsrt_base_url: str = GTFSRT_API_BASE_URL,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the client."""
        self._trip_semaphore = asyncio.Semaphore(TRIP_PAGE_CONCURRENCY)
        self._session = session
        self._owns_session = session is None
        self._jp_base_url = jp_base_url.rstrip("/")
        self._gtfsrt_base_url = gtfsrt_base_url.rstrip("/")
        self._now = now or (lambda: datetime.now(UTC))

    async def _get_session(self) -> aiohttp.ClientSession:
        """Ensure an active aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT})
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """Close the underlying session if owned."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def async_get_trip_timetable(self, trip_id: str) -> TripTimetable | None:
        """Fetch only one bounded public page; no script is ever executed."""
        from .trip_page import parse_trip_page

        if not trip_id or len(trip_id) > 128 or not trip_id.isprintable():
            raise TranslinkResponseError("Invalid trip ID")
        path = urllib.parse.quote(trip_id, safe="")
        url = URL(f"{self._jp_base_url}{ENDPOINT_TRIP_PAGE}{path}", encoded=True)
        session = await self._get_session()
        try:
            async with (
                self._trip_semaphore,
                session.get(
                    url,
                    headers={"Accept": "text/html"},
                    timeout=aiohttp.ClientTimeout(total=TRIP_PAGE_TIMEOUT),
                    allow_redirects=False,
                ) as response,
            ):
                if response.status != 200 or response.content_type != "text/html":
                    raise TranslinkResponseError("Trip page response was not HTML 200")
                if (
                    response.content_length is not None
                    and response.content_length > TRIP_PAGE_MAX_BYTES
                ):
                    raise TranslinkResponseError("Trip page exceeds size bound")
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > TRIP_PAGE_MAX_BYTES:
                        raise TranslinkResponseError("Trip page exceeds size bound")
                return parse_trip_page(body.decode("utf-8"), trip_id)
        except (TimeoutError, aiohttp.ClientError) as err:
            raise TranslinkConnectionError("Unable to fetch trip timetable") from err
        except UnicodeDecodeError as err:
            raise TranslinkResponseError("Invalid trip page encoding") from err

    async def fetch_stop_timetable(self, location_id: str) -> StopTimetable:
        """Fetch the timetable for the complete stored station or platform ID."""
        path = urllib.parse.quote(location_id, safe="")
        url = URL(f"{self._jp_base_url}{ENDPOINT_STOP_TIMETABLE}{path}", encoded=True)
        session = await self._get_session()
        try:
            async with session.get(
                url,
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise TranslinkResponseError(
                        f"Stop timetable failed with status {response.status}"
                    )
                if (
                    response.content_length is not None
                    and response.content_length > STOP_TIMETABLE_MAX_BYTES
                ):
                    raise TranslinkResponseError("Stop timetable exceeds size bound")
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > STOP_TIMETABLE_MAX_BYTES:
                        raise TranslinkResponseError(
                            "Stop timetable exceeds size bound"
                        )
                return StopTimetable.model_validate_json(body)
        except ValidationError as err:
            raise TranslinkResponseError("Invalid stop timetable response") from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise TranslinkConnectionError("Unable to fetch stop timetable") from err

    async def search_locations(self, query: str) -> list[LocationSearchResult]:
        """Search for stops, stations, and locations matching the query."""
        if not query or len(query.strip()) < 2:
            return []

        session = await self._get_session()
        url = f"{self._jp_base_url}{ENDPOINT_LOCATION_SEARCH}"
        params = {"location": query.strip()}

        try:
            async with session.get(
                url,
                params=params,
                headers={"Accept": "application/json, text/plain, */*"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    raise TranslinkResponseError(
                        f"Location search failed with status {response.status}"
                    )
                payload = await response.json()
                if not isinstance(payload, list):
                    return []
                try:
                    return [
                        LocationSearchResult.model_validate(item) for item in payload
                    ]
                except ValidationError as err:
                    raise TranslinkResponseError(
                        f"Failed to parse location search response: {err}"
                    ) from err
        except TimeoutError as err:
            raise TranslinkConnectionError(
                "Timed out connecting to Translink location search"
            ) from err
        except aiohttp.ClientError as err:
            raise TranslinkConnectionError(
                f"Error connecting to Translink location search: {err}"
            ) from err

    async def get_stops_by_geolocation(
        self, lat: float, lng: float, max_results: int = 10
    ) -> list[dict[str, Any]]:
        """Find nearby transit stops given latitude and longitude."""
        session = await self._get_session()
        url = f"{self._jp_base_url}{ENDPOINT_STOP_BY_GEOLOCATION}"
        params = {
            "lat": str(lat),
            "lng": str(lng),
            "maxResults": str(max_results),
        }

        try:
            async with session.get(
                url,
                params=params,
                headers={"Accept": "application/json, text/plain, */*"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    raise TranslinkResponseError(
                        f"Geolocation stop search failed with status {response.status}"
                    )
                data = await response.json()
                return data if isinstance(data, list) else []
        except TimeoutError as err:
            raise TranslinkConnectionError(
                "Timed out connecting to Translink geolocation stop search"
            ) from err
        except aiohttp.ClientError as err:
            raise TranslinkConnectionError(
                f"Error connecting to Translink geolocation stop search: {err}"
            ) from err

    def build_plan_request(
        self,
        start_location_id: str,
        start_name: str,
        end_location_id: str,
        end_name: str = "",
        transport_modes: list[str] | None = None,
        time_search_mode: str = "LeaveAfter",
        max_walking_distance: int = 4000,
        walking_speed: str = "Normal",
        target_datetime: datetime | None = None,
    ) -> JourneyPlanRequest:
        """Build the request used by the integration and raw CLI capture."""
        tz = ZoneInfo(BRISBANE_TZ)
        now_brisbane = (target_datetime or datetime.now(tz)).astimezone(tz)
        search_date = now_brisbane.strftime("%Y-%m-%d")
        search_time = now_brisbane.strftime("%-I:%M%p").lower()

        modes = transport_modes or ["Bus", "Ferry", "Train", "Tram"]

        # Build urlencoded parameters
        params: list[tuple[str, str]] = [
            ("searchDate", search_date),
            ("searchTime", search_time),
            ("startLocationId", start_location_id),
            ("start", start_name),
            ("endLocationId", end_location_id),
            ("end", end_name),
            ("timeSearchMode", time_search_mode),
            ("maximumWalkingDistance", str(max_walking_distance)),
            ("walkingSpeed", walking_speed),
        ]

        for m in modes:
            params.append(("transportModes", m))
        for st in ["Express", "NightLink", "Regular", "School"]:
            params.append(("serviceTypes", st))
        for ft in ["Free", "Prepaid", "Standard"]:
            params.append(("fareTypes", ft))

        body_string = urllib.parse.urlencode(params)
        plan_id = calculate_plan_hash(body_string)
        url = f"{self._jp_base_url}{ENDPOINT_PLAN}?id={plan_id}"

        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "Origin": self._jp_base_url,
            "Referer": f"{self._jp_base_url}/plan-your-journey/journey-planner",
        }
        return JourneyPlanRequest(url, body_string, plan_id, headers)

    async def plan_journey(
        self,
        start_location_id: str,
        start_name: str,
        end_location_id: str,
        end_name: str = "",
        transport_modes: list[str] | None = None,
        time_search_mode: str = "LeaveAfter",
        max_walking_distance: int = 4000,
        walking_speed: str = "Normal",
        target_datetime: datetime | None = None,
    ) -> JourneyPlanResult:
        """Plan journey between starting point and destination."""
        session = await self._get_session()
        request = self.build_plan_request(
            start_location_id,
            start_name,
            end_location_id,
            end_name,
            transport_modes,
            time_search_mode,
            max_walking_distance,
            walking_speed,
            target_datetime,
        )
        try:
            async with session.post(
                request.url,
                data=request.body,
                headers=request.headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    raise TranslinkResponseError(
                        f"Journey planner failed with status {response.status}"
                    )
                payload = await response.json()
                try:
                    return JourneyPlanResult.model_validate(payload)
                except ValidationError as err:
                    raise TranslinkResponseError(
                        f"Failed to parse journey planner response: {err}"
                    ) from err
        except TimeoutError as err:
            raise TranslinkConnectionError(
                "Timed out connecting to Translink journey planner"
            ) from err
        except aiohttp.ClientError as err:
            raise TranslinkConnectionError(
                f"Error connecting to Translink journey planner: {err}"
            ) from err

    async def _fetch_feed(
        self,
        path: str,
        parse: Callable[[bytes], _FeedRecords],
    ) -> tuple[int, _FeedRecords] | None:
        """Read and decode an optional GTFS realtime feed with a valid header."""
        session = await self._get_session()
        url = f"{self._gtfsrt_base_url}{path}"
        try:
            async with session.get(
                url,
                headers={"Accept": "application/x-protobuf"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    _LOGGER.debug("Realtime feed %s returned %s", path, response.status)
                    return None
                payload = await response.read()
            timestamp = parse_feed_timestamp(payload)
            return (timestamp, parse(payload)) if timestamp else None
        except (
            TimeoutError,
            aiohttp.ClientError,
            ValueError,
            OverflowError,
            IndexError,
        ) as err:
            _LOGGER.debug("Failed to read realtime feed %s: %r", path, err)
            return None

    async def fetch_vehicle_positions(
        self, region: str = DEFAULT_REALTIME_REGION
    ) -> tuple[VehiclePositionRecord, ...]:
        """Fetch live vehicle fixes in feed order, preserving collisions."""
        feed = REALTIME_FEED_REGIONS.get(region)
        if feed is None:
            return ()
        result = await self._fetch_feed(
            feed.vehicle_positions, parse_vehicle_position_records
        )
        if result is None:
            return ()
        timestamp, records = result
        now = self._now()
        if not _realtime_timestamp_is_fresh(timestamp, now):
            return ()
        return tuple(
            record
            for record in records
            if _realtime_timestamp_is_fresh(record.timestamp or timestamp, now)
        )

    async def fetch_trip_updates(
        self,
        region: str = DEFAULT_REALTIME_REGION,
        *,
        preserve_stale: bool = False,
    ) -> dict[str, TripUpdateRecord]:
        """Fetch live trip updates, optionally keeping stale timing provenance."""
        feed = REALTIME_FEED_REGIONS.get(region)
        if feed is None:
            return {}
        result = await self._fetch_feed(feed.trip_updates, parse_trip_updates)
        if result is None:
            return {}
        timestamp, records = result
        now = self._now()
        header_fresh = _realtime_timestamp_is_fresh(timestamp, now)
        if not header_fresh and not preserve_stale:
            return {}

        updates: dict[str, TripUpdateRecord] = {}
        for alias, record in records.items():
            observed_at = record.timestamp or timestamp
            if header_fresh and _realtime_timestamp_is_fresh(observed_at, now):
                updates[alias] = record
            elif preserve_stale:
                record.stale_timestamp = observed_at if header_fresh else timestamp
                updates[alias] = record
        return updates

    async def fetch_alerts(
        self, region: str = DEFAULT_REALTIME_REGION
    ) -> list[AlertRecord]:
        """Fetch service alerts from the selected regional feed."""
        feed = REALTIME_FEED_REGIONS.get(region)
        if feed is None:
            return []
        result = await self._fetch_feed(feed.alerts, parse_alerts)
        if result is None:
            return []
        timestamp, alerts = result
        return alerts if _realtime_timestamp_is_fresh(timestamp, self._now()) else []


def _match_trip_record(
    trip_id: str | None,
    records: dict[str, Any] | None,
    expected_route_id: str | None = None,
) -> Any | None:
    """Find matching GTFS-RT record by exact trip ID or normalized base trip ID."""
    if not trip_id or not records:
        return None
    if trip_id in records:
        return records[trip_id]
    base_id = extract_base_trip_id(trip_id)
    if base_id and base_id in records:
        record = records[base_id]
        record_route_id = getattr(record, "route_id", None)
        if (
            expected_route_id
            and record_route_id
            and record_route_id.split("-", 1)[0] != expected_route_id.split("-", 1)[0]
        ):
            return None
        parts = trip_id.split("_")
        service_date = parts[-2] if len(parts) > 2 else None
        feed_date = getattr(record, "start_date", None)
        if (
            service_date
            and len(service_date) == 8
            and service_date.isdigit()
            and feed_date
            and service_date != feed_date
        ):
            return None
        return record
    return None


def _planner_region_signals(leg: JourneyLeg) -> tuple[str, str]:
    route = leg.legRoute
    return (route.regionId or "", route.regionName or "") if route else ("", "")


def _leg_matches_feed(
    leg: JourneyLeg, feed: RealtimeFeedRegion, confirmed: bool
) -> bool:
    region_id, region_name = _planner_region_signals(leg)
    return (
        (confirmed or bool(region_id or region_name))
        and region_id in ("", feed.planner_region_id)
        and region_name in ("", feed.planner_region_name)
    )


def plan_matches_realtime_region(plan: JourneyPlanResult, region: str) -> bool:
    """Check a configured feed against planner signals on the first itinerary."""
    feed = REALTIME_FEED_REGIONS.get(region)
    if feed is None or not plan.itineraries:
        return True
    signalled = [
        leg
        for leg in plan.itineraries[0].legs
        if leg.travelMode.lower() != "walk" and any(_planner_region_signals(leg))
    ]
    return not signalled or any(
        _leg_matches_feed(leg, feed, False) for leg in signalled
    )


def _match_journey_update(
    leg: JourneyLeg,
    updates: dict[str, TripUpdateRecord] | None,
    strict_identity: bool,
) -> TripUpdateRecord | None:
    """Validate Cairns trip and boarding identity before exposing a live update."""
    trip_id = leg.tripId
    route = leg.legRoute.code if leg.legRoute else None
    if not strict_identity:
        return _match_trip_record(trip_id, updates, route)
    if not trip_id or not route or not updates or leg.origin is None:
        return None
    base_id = extract_base_trip_id(trip_id)
    record = updates.get(trip_id) or updates.get(base_id or "")
    if record is None or not base_id or extract_base_trip_id(record.trip_id) != base_id:
        return None
    feed_route = (record.route_id or "").split("-", 1)[0].removeprefix("C")
    planner_route = route.split("-", 1)[0].removeprefix("C")
    parts = trip_id.split("_")
    date = parts[-2] if len(parts) > 2 else ""
    if (
        not feed_route
        or feed_route != planner_route
        or len(date) != 8
        or not date.isascii()
        or not date.isdigit()
        or record.start_date != date
    ):
        return None
    origin = _stop_key(leg.origin.id)
    matches = [
        update
        for update in record.stop_time_updates
        if origin and _stop_key(update.stop_id) == origin
    ]
    if len(matches) != 1:
        return None
    visit = matches[0]
    event = visit.departure if visit.departure is not None else visit.arrival
    if (
        event is not None
        and event.time is not None
        and event.delay is not None
        and not _baseline_matches(
            visit,
            parse_iso_datetime(leg.departureTimeUtc),
            arrival=visit.departure is None,
        )
    ):
        return None
    return record


def vehicle_position_is_fresh(timestamp: float, now: datetime) -> bool:
    """Check the vehicle fix against the wall clock."""
    age = now.timestamp() - timestamp
    return (
        -VEHICLE_POSITION_MAX_FUTURE_SKEW_SECONDS
        <= age
        <= VEHICLE_POSITION_MAX_AGE_SECONDS
    )


def _match_vehicle_position(
    leg: JourneyLeg,
    positions: Mapping[str, VehiclePositionRecord] | Sequence[VehiclePositionRecord],
    now: datetime,
    validated_update: TripUpdateRecord | None = None,
) -> tuple[VehiclePositionRecord | None, VehiclePositionStatus]:
    """Accept a fresh fix only when one vehicle matches the active service."""
    trip_id = leg.tripId
    if not trip_id:
        return None, "no_position"
    base_id = extract_base_trip_id(trip_id)
    expected_route = leg.legRoute.code if leg.legRoute else None
    expected_prefix = expected_route.split("-", 1)[0] if expected_route else None
    parts = trip_id.split("_")
    service_date = parts[-2] if len(parts) > 2 else ""
    if len(service_date) != 8 or not service_date.isdigit():
        service_date = ""

    records = positions.values() if isinstance(positions, Mapping) else positions
    saw_match = False
    fresh: dict[tuple[str, str | int], tuple[int, VehiclePositionRecord]] = {}
    for record in records:
        if validated_update is not None:
            if record.trip_id != validated_update.trip_id or (
                record.vehicle_id
                and validated_update.vehicle_id
                and record.vehicle_id != validated_update.vehicle_id
            ):
                continue
        else:
            if record.trip_id != trip_id and (
                not base_id or extract_base_trip_id(record.trip_id) != base_id
            ):
                continue
            if (
                expected_prefix
                and record.route_id
                and expected_prefix != record.route_id.split("-", 1)[0]
            ):
                continue
            if service_date and record.start_date and service_date != record.start_date:
                continue
        saw_match = True
        timestamp = record.timestamp
        if timestamp is None or not vehicle_position_is_fresh(timestamp, now):
            continue
        if record.vehicle_id:
            identity: tuple[str, str | int] = ("vehicle", record.vehicle_id)
        elif record.entity_id:
            identity = ("entity", record.entity_id)
        else:
            identity = ("record", id(record))
        previous = fresh.get(identity)
        if previous is None or timestamp > previous[0]:
            fresh[identity] = (timestamp, record)

    if len(fresh) > 1:
        return None, "ambiguous"
    if fresh:
        return next(iter(fresh.values()))[1], "live"
    return None, "stale" if saw_match else "no_position"


def _stop_key(value: str | None) -> str:
    """Normalize observed SI prefixes and zero-padded bus IDs for matching only."""
    return (value or "").removeprefix("SI:").lstrip("0")


def _prediction_time(value: int | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def _realtime_stop(update: StopTimeUpdateRecord) -> CallingStopRealtime:
    relations: dict[int | None, StopRelationship] = {
        0: "scheduled",
        STOP_SKIPPED: "skipped",
        STOP_NO_DATA: "no_data",
    }
    relation = relations.get(update.schedule_relationship, "unknown")
    result = CallingStopRealtime(
        sequence=update.stop_sequence, scheduleRelationship=relation
    )
    if update.schedule_relationship == STOP_NO_DATA:
        return result
    for kind in ("arrival", "departure"):
        event = getattr(update, kind)
        if event is not None:
            setattr(result, f"{kind}TimeUtc", _prediction_time(event.time))
            setattr(result, f"{kind}DelaySeconds", event.delay)
            setattr(result, f"{kind}UncertaintySeconds", event.uncertainty)
    return result


def _baseline_matches(
    update: StopTimeUpdateRecord, target: datetime | None, *, arrival: bool = False
) -> bool:
    event = update.arrival if arrival else update.departure
    return bool(
        event is not None
        and event.time is not None
        and event.delay is not None
        and target is not None
        and event.time - event.delay == target.timestamp()
    )


def build_calling_stops(
    leg: JourneyLeg,
    timetable: TripTimetable | None,
    update: TripUpdateRecord | None,
) -> tuple[list[CallingStop], str, str | None]:
    """Join actual schedule calls to explicit feed occurrences, failing closed."""
    if (
        leg.travelMode.lower() == "walk"
        or leg.origin is None
        or leg.destination is None
    ):
        return [], "unavailable", None
    origin = _stop_key(leg.origin.id)
    destination = _stop_key(leg.destination.id)
    departure = parse_iso_datetime(leg.departureTimeUtc)
    arrival = parse_iso_datetime(leg.arrivalTimeUtc)
    if not origin or not destination:
        return [], "unavailable", None
    selected = []
    if timetable is not None and timetable.id == leg.tripId:
        starts = [
            i
            for i, stop in enumerate(timetable.departures)
            if _stop_key(stop.stopId) == origin
            and (
                departure is None
                or parse_iso_datetime(stop.scheduledDepartureUtc) == departure
            )
        ]
        ends = [
            i
            for i, stop in enumerate(timetable.departures)
            if _stop_key(stop.stopId) == destination
            and (
                arrival is None
                or parse_iso_datetime(stop.scheduledDepartureUtc) == arrival
            )
        ]
        if len(starts) == len(ends) == 1 and ends[0] > starts[0]:
            selected = timetable.departures[starts[0] : ends[0] + 1]
    calls: list[CallingStop] = []
    role: Literal["origin", "intermediate", "destination"]
    updates = update.stop_time_updates if update is not None else ()
    last_sequence: int | None = None
    for index, stop in enumerate(selected):
        alighting = stop.canBoardDebark == "Alighting"
        baseline = parse_iso_datetime(stop.scheduledDepartureUtc)
        candidates = [
            item
            for item in updates
            if _stop_key(item.stop_id) == _stop_key(stop.stopId)
            and (
                _baseline_matches(item, baseline, arrival=alighting)
                or (
                    item.schedule_relationship in (STOP_SKIPPED, STOP_NO_DATA)
                    and item.stop_sequence == stop.order
                )
            )
        ]
        if last_sequence is not None:
            candidates = [
                item
                for item in candidates
                if item.stop_sequence is not None and item.stop_sequence > last_sequence
            ]
        matched = candidates[0] if len(candidates) == 1 else None
        if matched is not None and matched.stop_sequence is not None:
            last_sequence = matched.stop_sequence
        role = (
            "origin"
            if index == 0
            else "destination"
            if index == len(selected) - 1
            else "intermediate"
        )
        calls.append(
            CallingStop(
                order=stop.order,
                stopId=stop.stopId,
                name=stop.name,
                platform=leg.origin.platform
                if role == "origin"
                else leg.destination.platform
                if role == "destination"
                else None,
                role=role,
                canBoardDebark=stop.canBoardDebark,
                scheduledTimeUtc=stop.scheduledDepartureUtc,
                realtime=_realtime_stop(matched) if matched is not None else None,
            )
        )
    if calls:
        has_realtime = any(stop.realtime is not None for stop in calls)
        return (
            calls,
            "scheduled_with_realtime" if has_realtime else "scheduled",
            _prediction_time(update.timestamp or update.feed_timestamp)
            if update is not None and has_realtime
            else None,
        )
    if not updates:
        return [], "unavailable", None
    # A partial feed is usable only when both endpoint occurrences are unique.
    starts = [
        i
        for i, stop in enumerate(updates)
        if _stop_key(stop.stop_id) == origin
        and (
            stop.departure is None
            or stop.departure.delay is None
            or _baseline_matches(stop, departure)
        )
    ]
    ends = [
        i
        for i, stop in enumerate(updates)
        if _stop_key(stop.stop_id) == destination
        and (
            stop.arrival is None
            or stop.arrival.delay is None
            or _baseline_matches(stop, arrival, arrival=True)
        )
    ]
    if len(starts) != 1 or len(ends) != 1 or ends[0] <= starts[0]:
        return [], "unavailable", None
    partial = updates[starts[0] : ends[0] + 1]
    names = {_stop_key(stop.id): stop.name for stop in leg.skippedStops}
    names[origin], names[destination] = leg.origin.name, leg.destination.name
    for index, visit in enumerate(partial):
        role = (
            "origin"
            if index == 0
            else "destination"
            if index == len(partial) - 1
            else "intermediate"
        )
        calls.append(
            CallingStop(
                stopId=visit.stop_id,
                name=names.get(_stop_key(visit.stop_id)),
                role=role,
                platform=leg.origin.platform
                if role == "origin"
                else leg.destination.platform
                if role == "destination"
                else None,
                realtime=_realtime_stop(visit),
            )
        )
    return (
        calls,
        "realtime_partial",
        _prediction_time(update.timestamp or update.feed_timestamp)
        if update is not None
        else None,
    )


class _DisruptionFields(TypedDict):
    """Disruption fields shared by both journey summary paths."""

    disruptions_count: int
    disruptions: list[dict[str, Any]]
    disruptions_description: str
    disruptions_summary: str
    latest_disruption_title: str | None
    latest_disruption_description: str | None


def _notice_expired(ends_utc: str | None, now: datetime) -> bool:
    """Treat missing, malformed and timezone-naive end times as unknown."""
    if not ends_utc:
        return False
    try:
        ends_at = datetime.fromisoformat(ends_utc)
    except ValueError:
        return False
    return ends_at.tzinfo is not None and now > ends_at


def _collect_leg_notices(
    itinerary: JourneyItinerary, notice_lookup: dict[str, PlanNotice]
) -> list[dict[str, Any]]:
    """Collect each usable leg notice once, enriched with planner details."""
    disruptions: list[dict[str, Any]] = []
    seen_notice_ids: set[str] = set()
    for leg in itinerary.legs:
        for notice in leg.notices:
            nid = str(notice.id) if notice.id is not None else None
            if nid and nid not in seen_notice_ids:
                seen_notice_ids.add(nid)
                detail = notice_lookup.get(nid)
                disruptions.append(
                    {
                        "id": notice.id,
                        "title": detail.title if detail else None,
                        "description": detail.description if detail else None,
                        "cause": detail.cause if detail else None,
                        "effect": detail.effect if detail else None,
                        "severity": notice.severity,
                        "starts_utc": detail.startsUtc if detail else None,
                        "ends_utc": detail.endsUtc if detail else None,
                        "leg": leg.travelMode,
                        "route": leg.legRoute.name if leg.legRoute else None,
                    }
                )

    return disruptions


def _collect_plan_notices(
    notices: list[PlanNotice], excluded: set[str]
) -> list[dict[str, Any]]:
    """Collect the first occurrence of each usable plan notice ID."""
    disruptions: list[dict[str, Any]] = []
    seen = set(excluded)
    for notice in notices:
        notice_id = str(notice.id) if notice.id is not None else None
        if notice_id and notice_id not in seen:
            seen.add(notice_id)
            disruptions.append(_unscoped_notice(notice, "Informative"))
    return disruptions


def _build_disruption_fields(
    notices: list[PlanNotice],
    itinerary: JourneyItinerary | None,
    now: datetime,
) -> _DisruptionFields:
    """Summarize leg notices or planner notices scoped to this request."""
    notice_lookup = {str(n.id): n for n in notices if n.id is not None}
    disruptions = _collect_leg_notices(itinerary, notice_lookup) if itinerary else []
    if not disruptions:
        disruptions = _collect_plan_notices(notices, set())

    return _format_disruptions(disruptions, now)


def _unscoped_notice(notice: PlanNotice, severity: str | None) -> dict[str, Any]:
    """Build the common notice shape when no leg supplies additional detail."""
    return {
        "id": notice.id,
        "title": notice.title,
        "description": notice.description,
        "cause": notice.cause,
        "effect": notice.effect,
        "severity": severity,
        "starts_utc": notice.startsUtc,
        "ends_utc": notice.endsUtc,
        "leg": None,
        "route": None,
    }


def stop_disruption_fields(
    alerts: TimetableServiceAlerts | None,
    previous: StopSummary | None,
    now: datetime,
) -> _DisruptionFields:
    """Format current stop alerts or retain the previous unavailable result."""
    if alerts is None and previous is not None:
        return {
            "disruptions_count": previous.disruptions_count,
            "disruptions": previous.disruptions,
            "disruptions_description": previous.disruptions_description,
            "disruptions_summary": previous.disruptions_summary,
            "latest_disruption_title": previous.latest_disruption_title,
            "latest_disruption_description": previous.latest_disruption_description,
        }

    notices: dict[str, dict[str, Any]] = {}
    for notice in alerts.current if alerts is not None else ():
        if notice.id is not None and notice.id != "":
            notices.setdefault(
                str(notice.id), _unscoped_notice(notice, notice.severity)
            )
    return _format_disruptions(list(notices.values()), now)


def _format_disruptions(
    disruptions: list[dict[str, Any]], now: datetime
) -> _DisruptionFields:
    """Apply expiry and format normalized notices for entities."""
    # Apply expiry after choosing the notice scope and winning detail.
    disruptions = [d for d in disruptions if not _notice_expired(d["ends_utc"], now)]
    titles = [str(d["title"]) for d in disruptions if d.get("title")]
    descriptions = [str(d["description"]) for d in disruptions if d.get("description")]
    disruptions_summary = "; ".join(titles) if titles else "Normal"
    disruptions_description = (
        "\n".join(
            f"• {d['title']}: {d['description']}"
            if d.get("title") and d.get("description")
            else str(d.get("title") or d.get("description") or "Disruption")
            for d in disruptions
        )
        if disruptions
        else "No active disruptions"
    )
    return {
        "disruptions_count": len(disruptions),
        "disruptions": disruptions,
        "disruptions_description": disruptions_description,
        "disruptions_summary": disruptions_summary,
        "latest_disruption_title": titles[0] if titles else None,
        "latest_disruption_description": descriptions[0] if descriptions else None,
    }


type JourneySort = Literal["departure", "arrival", "duration"]


class AlternativeLeg(TypedDict):
    """Compact schedule for one planner leg."""

    mode: str
    route_code: str | None
    route_name: str | None
    headsign: str | None
    origin: str | None
    destination: str | None
    departure: str | None
    arrival: str | None


class JourneyAlternative(TypedDict):
    """One scheduled itinerary in an on-demand journey plan."""

    planner_index: int
    planner_first: bool
    departure: str | None
    arrival: str | None
    duration_mins: int | None
    transfers: int | None
    legs: list[AlternativeLeg]
    legs_truncated: bool
    notices: list[dict[str, Any]]


class JourneyAlternatives(TypedDict):
    """Bounded response from on-demand journey planning."""

    sort_by: JourneySort
    total_alternatives: int
    returned: int
    truncated: bool
    alternatives: list[JourneyAlternative]
    plan_notices: list[dict[str, Any]]


def _scheduled_time(value: str | None) -> str | None:
    """Normalize an aware planner time without using the host timezone."""
    if not value:
        return None
    try:
        if datetime.fromisoformat(value).tzinfo is None:
            return None
        parsed = parse_iso_datetime(value)
    except (ValueError, OverflowError):
        return None
    return parsed.isoformat() if parsed is not None else None


def _alternative_leg(leg: JourneyLeg) -> AlternativeLeg:
    """Expose only the scheduled fields needed to compare routes."""
    return {
        "mode": leg.travelMode,
        "route_code": leg.legRoute.code if leg.legRoute else None,
        "route_name": leg.legRoute.name if leg.legRoute else None,
        "headsign": leg.tripHeadsign,
        "origin": leg.origin.name if leg.origin else None,
        "destination": leg.destination.name if leg.destination else None,
        "departure": _scheduled_time(leg.departureTimeUtc),
        "arrival": _scheduled_time(leg.arrivalTimeUtc),
    }


_ALTERNATIVE_SORT_KEYS: dict[
    JourneySort, tuple[Literal["departure", "arrival", "duration_mins"], ...]
] = {
    "departure": ("departure", "arrival", "duration_mins"),
    "arrival": ("arrival", "departure", "duration_mins"),
    "duration": ("duration_mins", "departure", "arrival"),
}


def _alternative_sort_key(
    alternative: JourneyAlternative, sort_by: JourneySort
) -> tuple[tuple[bool, str | int], ...]:
    # Each position compares the same type. UTC strings sort chronologically.
    return (
        *(
            (value is None, value if value is not None else 0)
            for key in _ALTERNATIVE_SORT_KEYS[sort_by]
            for value in (alternative[key],)
        ),
        (False, alternative["planner_index"]),
    )


def build_journey_alternatives(
    plan: JourneyPlanResult, sort_by: JourneySort, limit: int
) -> JourneyAlternatives:
    """Return bounded, sorted schedules from one planner response."""
    notice_lookup = {str(n.id): n for n in plan.notices if n.id is not None}
    referenced_notices: set[str] = set()
    alternatives: list[JourneyAlternative] = []

    for index, itinerary in enumerate(plan.itineraries):
        notices = _collect_leg_notices(itinerary, notice_lookup)
        referenced_notices.update(str(notice["id"]) for notice in notices)
        duration = itinerary.durationMins
        alternatives.append(
            {
                "planner_index": index,
                "planner_first": index == 0,
                "departure": _scheduled_time(itinerary.firstDepartureTimeUtc),
                "arrival": _scheduled_time(itinerary.lastArrivalTimeUtc),
                "duration_mins": (
                    duration
                    if "durationMins" in itinerary.model_fields_set and duration >= 0
                    else None
                ),
                "transfers": (
                    max(
                        0,
                        sum(leg.travelMode.lower() != "walk" for leg in itinerary.legs)
                        - 1,
                    )
                    if itinerary.legs
                    else None
                ),
                "legs": [
                    _alternative_leg(leg)
                    for leg in itinerary.legs[:MAX_ALTERNATIVE_LEGS]
                ],
                "legs_truncated": len(itinerary.legs) > MAX_ALTERNATIVE_LEGS,
                "notices": notices[:MAX_ALTERNATIVE_NOTICES],
            }
        )

    alternatives.sort(key=lambda option: _alternative_sort_key(option, sort_by))
    limited = alternatives[: min(MAX_ALTERNATIVES_LIMIT, max(1, limit))]
    return {
        "sort_by": sort_by,
        "total_alternatives": len(alternatives),
        "returned": len(limited),
        "truncated": len(limited) < len(alternatives),
        "alternatives": limited,
        "plan_notices": _collect_plan_notices(plan.notices, referenced_notices)[
            :MAX_ALTERNATIVE_NOTICES
        ],
    }


@dataclass(frozen=True, slots=True)
class _EndpointPrediction:
    status: RealtimeStatus = "unavailable"
    delay_seconds: int | None = None
    source: DelaySource | None = None
    relationship: StopRelationship | None = None
    updated_at: datetime | None = None


def _realtime_timestamp_is_fresh(timestamp: int, now: datetime) -> bool:
    age = now.timestamp() - timestamp
    return -REALTIME_MAX_FUTURE_SKEW_SECONDS <= age <= REALTIME_MAX_AGE_SECONDS


def _realtime_freshness(
    record: TripUpdateRecord, now: datetime
) -> tuple[datetime | None, Literal["fresh", "stale", "unknown"]]:
    """Use the trip's timestamp before the less specific feed timestamp."""
    if record.stale_timestamp is not None:
        return parse_iso_datetime(_prediction_time(record.stale_timestamp)), "stale"
    timestamp = record.timestamp or record.feed_timestamp
    if not timestamp:
        return None, "unknown"
    updated_at = parse_iso_datetime(_prediction_time(timestamp))
    if not _realtime_timestamp_is_fresh(timestamp, now):
        return updated_at, "stale"
    return updated_at, "fresh"


def _trip_delay_applies(record: TripUpdateRecord) -> bool:
    """Allow trip-level timing only if the feed has no more specific timing."""
    return record.trip_delay_seconds is not None and not any(
        update.schedule_relationship == STOP_NO_DATA
        or any(
            event is not None and (event.time is not None or event.delay is not None)
            for event in (update.arrival, update.departure)
        )
        for update in record.stop_time_updates
    )


def _previous_timetable_update(
    updates: tuple[StopTimeUpdateRecord, ...], timetable: TripTimetable, order: int
) -> StopTimeUpdateRecord | None:
    """Find the closest earlier update whose occurrence is proven by the timetable."""
    orders_by_stop: dict[str, list[int]] = {}
    for stop in timetable.departures:
        orders_by_stop.setdefault(_stop_key(stop.stopId), []).append(stop.order)
    for visit in reversed(updates):
        orders = orders_by_stop.get(_stop_key(visit.stop_id), [])
        if len(orders) == 1:
            visit_order = orders[0]
        elif visit.stop_sequence in orders:
            visit_order = visit.stop_sequence
        else:
            continue
        if visit_order <= order:
            return visit if visit_order < order else None
    return None


def _endpoint_prediction(
    leg: JourneyLeg,
    record: TripUpdateRecord | None,
    timetable: TripTimetable | None,
    scheduled_calls: list[CallingStop],
    updated_at: datetime | None,
    freshness: Literal["fresh", "stale", "unknown"],
    *,
    arrival: bool,
    allow_trip_delay: bool,
) -> _EndpointPrediction:
    """Find the prediction for one particular stop visit."""
    if record is None:
        return _EndpointPrediction()
    if freshness == "stale":
        return _EndpointPrediction("stale", updated_at=updated_at)
    if record.trip_schedule_relationship in (TRIP_CANCELED, TRIP_DELETED):
        return _EndpointPrediction("no_prediction", updated_at=updated_at)
    stop = leg.destination if arrival else leg.origin
    key = _stop_key(stop.id if stop is not None else None)
    scheduled = parse_iso_datetime(
        leg.arrivalTimeUtc if arrival else leg.departureTimeUtc
    )
    candidates = [
        update
        for update in record.stop_time_updates
        if key and _stop_key(update.stop_id) == key
    ]
    event: CallingStopRealtime | None = None
    if scheduled_calls and timetable is not None:
        call = scheduled_calls[-1 if arrival else 0]
        event = call.realtime
        if event is None:
            assert call.order is not None  # A scheduled call has a timetable order.
            preceding = _previous_timetable_update(
                record.stop_time_updates, timetable, call.order
            )
            if (
                preceding is not None
                and preceding.schedule_relationship == STOP_NO_DATA
            ):
                return _EndpointPrediction(
                    "no_data", relationship="no_data", updated_at=updated_at
                )
    elif len(candidates) == 1:
        candidate = candidates[0]
        if candidate.schedule_relationship in (STOP_SKIPPED, STOP_NO_DATA) or (
            _baseline_matches(candidate, scheduled, arrival=arrival)
        ):
            event = _realtime_stop(candidate)

    relationship = event.scheduleRelationship if event is not None else None
    if relationship == "no_data":
        return _EndpointPrediction(
            "no_data", relationship=relationship, updated_at=updated_at
        )
    if relationship == "skipped":
        return _EndpointPrediction(
            "no_prediction", relationship=relationship, updated_at=updated_at
        )
    if event is not None:
        event_delay = (
            event.arrivalDelaySeconds if arrival else event.departureDelaySeconds
        )
        event_time = parse_iso_datetime(
            event.arrivalTimeUtc if arrival else event.departureTimeUtc
        )
        if (
            event_delay is not None
            and event_time is not None
            and scheduled is not None
            and event_time.timestamp() - event_delay == scheduled.timestamp()
        ):
            return _EndpointPrediction(
                "live", event_delay, "stop_event", relationship, updated_at
            )
    if (
        allow_trip_delay
        and scheduled is not None
        and len(candidates) <= 1
        and _trip_delay_applies(record)
    ):
        return _EndpointPrediction(
            "live", record.trip_delay_seconds, "trip", updated_at=updated_at
        )
    return _EndpointPrediction(
        "no_prediction", relationship=relationship, updated_at=updated_at
    )


def _predicted_boundary(
    scheduled: datetime | None, endpoint: _EndpointPrediction
) -> datetime | None:
    if scheduled is None or endpoint.delay_seconds is None:
        return None
    return scheduled + timedelta(seconds=endpoint.delay_seconds)


def _active_transit_leg(
    legs: list[JourneyLeg],
    alighting_predictions: dict[int, _EndpointPrediction],
    now: datetime,
) -> tuple[int | None, JourneyLeg | None]:
    """Select the first transit leg whose effective arrival has not passed."""
    for index, leg in enumerate(legs):
        if leg.travelMode.lower() == "walk":
            continue
        scheduled = parse_iso_datetime(leg.arrivalTimeUtc)
        if scheduled is None:
            return index, leg
        prediction = alighting_predictions[index]
        predicted = (
            _predicted_boundary(scheduled, prediction)
            if prediction.source == "stop_event"
            else None
        )
        if now <= max(scheduled, predicted or scheduled):
            return index, leg
    return None, None


def build_journey_summary(
    plan: JourneyPlanResult,
    vehicle_positions: Mapping[str, VehiclePositionRecord]
    | Sequence[VehiclePositionRecord]
    | None = None,
    trip_updates: dict[str, TripUpdateRecord] | None = None,
    fare_preference: str = "Adult",
    origin_name_fallback: str = "",
    destination_name_fallback: str = "",
    now: datetime | None = None,
    *,
    trip_timetables: dict[str, TripTimetable] | None = None,
    track_vehicle: bool = True,
    realtime_region: str = DEFAULT_REALTIME_REGION,
    region_confirmed: bool = True,
) -> JourneySummary:
    """Build a unified presentation summary for Home Assistant sensors."""
    if now is None:
        now = datetime.now(UTC)

    itinerary = plan.itineraries[0] if plan.itineraries else None
    disruption_fields = _build_disruption_fields(plan.notices, itinerary, now)
    if itinerary is None:
        return JourneySummary(
            status="no_service",
            vehicle_position_status="no_active_leg" if track_vehicle else "disabled",
            origin_name=origin_name_fallback,
            destination_name=destination_name_fallback,
            last_updated=now,
            **disruption_fields,
        )

    departure_time = parse_iso_datetime(itinerary.firstDepartureTimeUtc)
    arrival_time = parse_iso_datetime(itinerary.lastArrivalTimeUtc)

    # Find the primary transit leg (first non-walking leg, or first leg)
    transit_legs = [leg for leg in itinerary.legs if leg.travelMode.lower() != "walk"]
    primary_leg = (
        transit_legs[0]
        if transit_legs
        else (itinerary.legs[0] if itinerary.legs else None)
    )

    transfers = max(0, len(transit_legs) - 1)

    next_service_name: str | None = None
    next_service_vehicle: str | None = None
    next_service_headsign: str | None = None
    next_service_route_code: str | None = None
    next_service_color: str | None = None
    operator: str | None = None
    origin_name = origin_name_fallback
    origin_platform: str | None = None
    destination_name = destination_name_fallback
    destination_platform: str | None = None
    trip_id: str | None = None
    polyline: str | None = None

    if primary_leg:
        trip_id = primary_leg.tripId
        polyline = primary_leg.polyline
        if primary_leg.legRoute:
            next_service_name = primary_leg.legRoute.name
            next_service_vehicle = primary_leg.legRoute.vehicle
            next_service_headsign = primary_leg.legRoute.headsign
            next_service_route_code = primary_leg.legRoute.code
            next_service_color = primary_leg.legRoute.hexColorCode
            operator = primary_leg.legRoute.operator
        else:
            next_service_name = primary_leg.travelMode
            next_service_vehicle = primary_leg.travelMode

        if primary_leg.origin:
            origin_name = primary_leg.origin.name or origin_name_fallback
            origin_platform = primary_leg.origin.platform

    last_leg = itinerary.legs[-1] if itinerary.legs else None
    if last_leg and last_leg.destination:
        destination_name = last_leg.destination.name or destination_name_fallback
        destination_platform = last_leg.destination.platform

    # Calculate walking distance
    walking_distance = sum(
        leg.distanceM for leg in itinerary.legs if leg.travelMode.lower() == "walk"
    )

    # Process fares
    fare_price: float | None = None
    fare_type_chosen: str | None = None
    fares_breakdown: list[dict[str, Any]] = []

    is_concession = "concession" in fare_preference.lower()
    for fare in itinerary.fares:
        fares_breakdown.append(
            {"type": fare.type, "name": fare.name, "price": fare.price}
        )
        if fare_price is None and (
            (
                is_concession
                and "concession" in fare.type.lower()
                and "paper" not in fare.type.lower()
            )
            or (
                not is_concession
                and "adult" in fare.type.lower()
                and "paper" not in fare.type.lower()
            )
        ):
            fare_price = fare.price
            fare_type_chosen = fare.name

    if fare_price is None and itinerary.fares:
        fare_price = itinerary.fares[0].price
        fare_type_chosen = itinerary.fares[0].name

    # Detailed legs representation
    legs_summary: list[dict[str, Any]] = []
    boarding = alighting = _EndpointPrediction()
    alighting_predictions: dict[int, _EndpointPrediction] = {}
    cancelled = False
    feed = REALTIME_FEED_REGIONS.get(realtime_region)
    strict_identity = feed is not None and feed.strict_identity
    eligible_legs: set[int] = set()
    fresh_updates: dict[int, TripUpdateRecord] = {}
    for index, leg in enumerate(itinerary.legs):
        is_transit = leg.travelMode.lower() != "walk"
        matched_update = None
        if (
            is_transit
            and feed is not None
            and _leg_matches_feed(leg, feed, region_confirmed)
        ):
            eligible_legs.add(index)
            matched_update = _match_journey_update(leg, trip_updates, strict_identity)
        updated_at, freshness = (
            _realtime_freshness(matched_update, now)
            if matched_update is not None
            else (None, "unknown")
        )
        timetable = (trip_timetables or {}).get(leg.tripId or "")
        usable_update = matched_update if freshness != "stale" else None
        calls, source, updated = build_calling_stops(leg, timetable, usable_update)
        schedule_relationship = None
        if is_transit:
            if usable_update is not None:
                fresh_updates[index] = usable_update
                schedule_relationship = usable_update.trip_schedule_relationship
            scheduled_calls = (
                calls if source in ("scheduled_with_realtime", "scheduled") else []
            )
            if leg is transit_legs[0]:
                boarding = _endpoint_prediction(
                    leg,
                    matched_update,
                    timetable,
                    scheduled_calls,
                    updated_at,
                    freshness,
                    arrival=False,
                    allow_trip_delay=not strict_identity,
                )
            leg_alighting = _endpoint_prediction(
                leg,
                matched_update,
                timetable,
                scheduled_calls,
                updated_at,
                freshness,
                arrival=True,
                allow_trip_delay=not strict_identity,
            )
            alighting_predictions[index] = leg_alighting
            if leg is transit_legs[-1]:
                alighting = leg_alighting
        leg_cancelled = schedule_relationship in (TRIP_CANCELED, TRIP_DELETED)
        cancelled |= leg_cancelled
        legs_summary.append(
            {
                "travelMode": leg.travelMode,
                "durationMins": leg.durationMins,
                "distanceM": leg.distanceM,
                "departureTimeUtc": leg.departureTimeUtc,
                "arrivalTimeUtc": leg.arrivalTimeUtc,
                "origin": leg.origin.name if leg.origin else None,
                "originPlatform": leg.origin.platform if leg.origin else None,
                "destination": leg.destination.name if leg.destination else None,
                "destinationPlatform": leg.destination.platform
                if leg.destination
                else None,
                "route": leg.legRoute.name if leg.legRoute else None,
                "routeCode": leg.legRoute.code if leg.legRoute else None,
                "routeColor": leg.legRoute.hexColorCode if leg.legRoute else None,
                "operator": leg.legRoute.operator if leg.legRoute else None,
                "numberOfStops": leg.numberOfStops,
                "skippedStops": [s.name for s in leg.skippedStops],
                "callingStops": [stop.model_dump() for stop in calls],
                "callingStopsSource": source,
                "callingStopsRealtimeUpdatedAt": updated,
                **(
                    {
                        "tripCancelled": leg_cancelled,
                        "tripScheduleRelationship": schedule_relationship,
                    }
                    if is_transit
                    else {}
                ),
            }
        )

    delay_mins = (
        round(boarding.delay_seconds / 60)
        if boarding.delay_seconds is not None
        else None
    )
    status: JourneyStatus = "scheduled"
    predicted_departure = _predicted_boundary(departure_time, boarding)
    predicted_arrival = _predicted_boundary(arrival_time, alighting)
    effective_departure = predicted_departure or departure_time
    effective_arrival = predicted_arrival or arrival_time
    if cancelled:
        status = "cancelled"
    elif boarding.relationship == "skipped":
        status = "boarding_skipped"
    elif effective_departure and effective_arrival:
        effective_arrival = max(effective_departure, effective_arrival)
        if now > effective_arrival:
            status = "arrived"
        elif effective_departure <= now:
            status = "departed"
        elif delay_mins is not None:
            if delay_mins >= DELAYED_THRESHOLD_MINUTES:
                status = "delayed"
            elif delay_mins <= EARLY_THRESHOLD_MINUTES:
                status = "early"
            else:
                status = "on_time"

    evidence = boarding
    if boarding.status != "stale" and (
        alighting.status == "stale"
        or boarding.status == "unavailable"
        or (
            boarding.status == "no_prediction"
            and boarding.relationship is None
            and alighting.status in ("live", "no_data")
        )
    ):
        evidence = alighting

    active_index, active_leg = _active_transit_leg(
        itinerary.legs, alighting_predictions, now
    )
    active_route = active_leg.legRoute if active_leg is not None else None
    active_mode = active_leg.travelMode if active_leg is not None else None
    vehicle = None
    position_status: VehiclePositionStatus = "no_active_leg"
    if not track_vehicle:
        position_status = "disabled"
    elif active_leg is not None and active_index is not None:
        position_status = "no_position"
        validated_update = fresh_updates.get(active_index) if strict_identity else None
        if active_index in eligible_legs and (
            not strict_identity or validated_update is not None
        ):
            vehicle, position_status = _match_vehicle_position(
                active_leg, vehicle_positions or (), now, validated_update
            )

    return JourneySummary(
        status=status,
        departure_time=departure_time,
        arrival_time=arrival_time,
        duration_mins=itinerary.durationMins,
        transfers=transfers,
        next_service_name=next_service_name,
        next_service_vehicle=next_service_vehicle,
        next_service_headsign=next_service_headsign,
        next_service_route_code=next_service_route_code,
        next_service_color=next_service_color,
        operator=operator,
        origin_name=origin_name,
        origin_platform=origin_platform,
        destination_name=destination_name,
        destination_platform=destination_platform,
        fare_price=fare_price,
        fare_currency="AUD",
        fare_type=fare_type_chosen,
        fares_breakdown=fares_breakdown,
        walking_distance_m=walking_distance,
        delay_mins=delay_mins,
        departure_delay_seconds=boarding.delay_seconds,
        arrival_delay_seconds=alighting.delay_seconds,
        realtime_status=evidence.status,
        realtime_updated_at=evidence.updated_at,
        delay_source=boarding.source,
        predicted_departure_time=predicted_departure,
        predicted_arrival_time=predicted_arrival,
        boarding_relationship=boarding.relationship,
        alighting_skipped=alighting.relationship == "skipped",
        trip_id=trip_id,
        active_leg_index=active_index,
        active_trip_id=active_leg.tripId if active_leg is not None else None,
        active_route_name=active_route.name
        if active_route is not None
        else active_mode,
        active_route_code=active_route.code if active_route is not None else None,
        active_route_color=active_route.hexColorCode
        if active_route is not None
        else None,
        active_vehicle_type=active_route.vehicle
        if active_route is not None
        else active_mode,
        vehicle_position_status=position_status,
        vehicle_position_timestamp=_prediction_time(vehicle.timestamp)
        if vehicle
        else None,
        vehicle_id=(vehicle.vehicle_id or vehicle.entity_id) if vehicle else None,
        vehicle_label=vehicle.vehicle_label if vehicle else None,
        vehicle_latitude=vehicle.latitude if vehicle else None,
        vehicle_longitude=vehicle.longitude if vehicle else None,
        vehicle_bearing=vehicle.bearing if vehicle else None,
        vehicle_speed=vehicle.speed if vehicle else None,
        vehicle_tracked=position_status == "live",
        polyline=polyline,
        itinerary_legs=legs_summary,
        last_updated=now,
        **disruption_fields,
    )
