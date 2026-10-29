"""API client and data processing helpers for Translink Queensland."""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

import aiohttp
from pydantic import ValidationError
from yarl import URL

from ..const import (
    BRISBANE_TZ,
    ENDPOINT_LOCATION_SEARCH,
    ENDPOINT_PLAN,
    ENDPOINT_STOP_BY_GEOLOCATION,
    ENDPOINT_TRIP_PAGE,
    GTFS_FEED_ALERTS,
    GTFS_FEED_TRIP_UPDATES,
    GTFS_FEED_VEHICLE_POSITIONS,
    GTFSRT_API_BASE_URL,
    JP_API_BASE_URL,
    TRIP_PAGE_CONCURRENCY,
    TRIP_PAGE_MAX_BYTES,
    TRIP_PAGE_TIMEOUT,
)
from .gtfs_realtime import (
    AlertRecord,
    StopTimeUpdateRecord,
    TripUpdateRecord,
    VehiclePositionRecord,
    extract_base_trip_id,
    parse_alerts,
    parse_trip_updates,
    parse_vehicle_positions,
)
from .models import (
    CallingStop,
    CallingStopRealtime,
    JourneyLeg,
    JourneyPlanResult,
    JourneyStatus,
    JourneySummary,
    LocationSearchResult,
    TripTimetable,
)

_LOGGER = logging.getLogger(__name__)

USER_AGENT = "HomeAssistant-Translink/2026.10.0"


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
    ) -> None:
        """Initialize the client."""
        self._trip_semaphore = asyncio.Semaphore(TRIP_PAGE_CONCURRENCY)
        self._session = session
        self._owns_session = session is None
        self._jp_base_url = jp_base_url.rstrip("/")
        self._gtfsrt_base_url = gtfsrt_base_url.rstrip("/")

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
                    text = await response.text()
                    raise TranslinkResponseError(
                        f"Location search failed with status {response.status}: {text}"
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
                    text = await response.text()
                    raise TranslinkResponseError(
                        f"Geolocation stop search failed with status {response.status}: {text}"
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

        try:
            async with session.post(
                url,
                data=body_string,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    raise TranslinkResponseError(
                        f"Journey planner failed with status {response.status}: {text}"
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

    async def fetch_vehicle_positions(self) -> dict[str, VehiclePositionRecord]:
        """Fetch and parse live vehicle positions from Translink GTFS-RT feed."""
        session = await self._get_session()
        url = f"{self._gtfsrt_base_url}{GTFS_FEED_VEHICLE_POSITIONS}"

        try:
            async with session.get(
                url,
                headers={"Accept": "application/x-protobuf"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    _LOGGER.warning(
                        "VehiclePositions feed returned status %s", response.status
                    )
                    return {}
                data = await response.read()
                return parse_vehicle_positions(data)
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.debug("Failed to fetch live vehicle positions feed: %r", err)
            return {}

    async def fetch_trip_updates(self) -> dict[str, TripUpdateRecord]:
        """Fetch and parse live trip delays from Translink GTFS-RT feed."""
        session = await self._get_session()
        url = f"{self._gtfsrt_base_url}{GTFS_FEED_TRIP_UPDATES}"

        try:
            async with session.get(
                url,
                headers={"Accept": "application/x-protobuf"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    _LOGGER.warning(
                        "TripUpdates feed returned status %s", response.status
                    )
                    return {}
                data = await response.read()
                return parse_trip_updates(data)
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.debug("Failed to fetch live trip updates feed: %r", err)
            return {}

    async def fetch_alerts(self) -> list[AlertRecord]:
        """Fetch and parse live service disruptions from Translink GTFS-RT feed."""
        session = await self._get_session()
        url = f"{self._gtfsrt_base_url}{GTFS_FEED_ALERTS}"

        try:
            async with session.get(
                url,
                headers={"Accept": "application/x-protobuf"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    return []
                data = await response.read()
                return parse_alerts(data)
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.debug("Failed to fetch live alerts feed: %r", err)
            return []


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
    relations: dict[
        int | None, Literal["scheduled", "skipped", "no_data", "unknown"]
    ] = {0: "scheduled", 1: "skipped", 2: "no_data"}
    relation = relations.get(update.schedule_relationship, "unknown")
    result = CallingStopRealtime(
        sequence=update.stop_sequence, scheduleRelationship=relation
    )
    if update.schedule_relationship == 2:
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
                    item.schedule_relationship in (1, 2)
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
            _prediction_time(update.timestamp)
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
        _prediction_time(update.timestamp) if update is not None else None,
    )


def build_journey_summary(
    plan: JourneyPlanResult,
    vehicle_positions: dict[str, VehiclePositionRecord] | None = None,
    trip_updates: dict[str, TripUpdateRecord] | None = None,
    fare_preference: str = "Adult",
    origin_name_fallback: str = "",
    destination_name_fallback: str = "",
    now: datetime | None = None,
    *,
    trip_timetables: dict[str, TripTimetable] | None = None,
) -> JourneySummary:
    """Build a unified presentation summary for Home Assistant sensors."""
    if now is None:
        now = datetime.now(UTC)

    if not plan.itineraries:
        return JourneySummary(
            status="no_service",
            origin_name=origin_name_fallback,
            destination_name=destination_name_fallback,
            last_updated=now,
        )

    itinerary = plan.itineraries[0]
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

    # Check delays via TripUpdates
    delay_mins = 0
    tu = _match_trip_record(
        trip_id, trip_updates, expected_route_id=next_service_route_code
    )
    if tu is not None:
        delay_mins = max(0, round(tu.delay_seconds / 60))

    # Determine status
    status: JourneyStatus = "scheduled"
    if departure_time and arrival_time:
        if now > arrival_time:
            status = "arrived"
        elif departure_time <= now <= arrival_time:
            status = "departed"
        elif delay_mins >= 3:
            status = "delayed"
        else:
            status = "on_time"

    # Correlate live vehicle tracking via VehiclePositions
    veh_id: str | None = None
    veh_label: str | None = None
    veh_lat: float | None = None
    veh_lng: float | None = None
    veh_bearing: float | None = None
    veh_speed: float | None = None
    veh_tracked = False

    vp = _match_trip_record(
        trip_id, vehicle_positions, expected_route_id=next_service_route_code
    )
    if vp is not None:
        veh_id = vp.vehicle_id or vp.entity_id
        veh_label = vp.vehicle_label
        veh_lat = vp.latitude
        veh_lng = vp.longitude
        veh_bearing = vp.bearing
        veh_speed = vp.speed
        veh_tracked = True
    elif primary_leg and primary_leg.origin and primary_leg.origin.position:
        # Fallback to origin platform/station coordinates
        veh_lat = primary_leg.origin.position.lat
        veh_lng = primary_leg.origin.position.lng

    # Map notices by id from plan.notices
    notice_lookup = {str(n.id): n for n in plan.notices if n.id is not None}

    # Aggregate disruptions
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

    if not disruptions and plan.notices:
        for n in plan.notices:
            nid = str(n.id) if n.id is not None else None
            if nid and nid not in seen_notice_ids:
                seen_notice_ids.add(nid)
                disruptions.append(
                    {
                        "id": n.id,
                        "title": n.title,
                        "description": n.description,
                        "cause": n.cause,
                        "effect": n.effect,
                        "severity": "Informative",
                        "starts_utc": n.startsUtc,
                        "ends_utc": n.endsUtc,
                        "leg": None,
                        "route": None,
                    }
                )

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
    latest_disruption_title = titles[0] if titles else None
    latest_disruption_description = descriptions[0] if descriptions else None

    # Detailed legs representation
    legs_summary: list[dict[str, Any]] = []
    for leg in itinerary.legs:
        matched_update = _match_trip_record(
            leg.tripId, trip_updates, leg.legRoute.code if leg.legRoute else None
        )
        calls, source, updated = build_calling_stops(
            leg, (trip_timetables or {}).get(leg.tripId or ""), matched_update
        )
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
            }
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
        disruptions_count=len(disruptions),
        disruptions=disruptions,
        disruptions_description=disruptions_description,
        disruptions_summary=disruptions_summary,
        latest_disruption_title=latest_disruption_title,
        latest_disruption_description=latest_disruption_description,
        trip_id=trip_id,
        vehicle_id=veh_id,
        vehicle_label=veh_label,
        vehicle_latitude=veh_lat,
        vehicle_longitude=veh_lng,
        vehicle_bearing=veh_bearing,
        vehicle_speed=veh_speed,
        vehicle_tracked=veh_tracked,
        polyline=polyline,
        itinerary_legs=legs_summary,
        last_updated=now,
    )
