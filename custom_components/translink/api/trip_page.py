"""Bounded, inert decoding of the public timetable page's Flight records."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from typing import Any

from pydantic import ValidationError

from ..const import TRIP_PAGE_MAX_BYTES
from .client import TranslinkApiError
from .models import TripTimetable

MAX_RECORDS = 4096
MAX_NODES = 50000
MAX_DEPTH = 80
PUSH_PREFIX = "self.__next_f.push("


class TripPageParseError(TranslinkApiError):
    """The upstream page no longer contains a safe, unambiguous timetable."""


class _FlightScripts(HTMLParser):
    """Collect literal string pushes without evaluating any JavaScript."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.script: str | None = None
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.script = ""

    def handle_data(self, data: str) -> None:
        if self.script is not None:
            self.script += data

    def handle_endtag(self, tag: str) -> None:
        if tag != "script" or self.script is None:
            return
        script = self.script.strip()
        self.script = None
        if not script.startswith(PUSH_PREFIX):
            return
        if not script.endswith(")"):
            raise TripPageParseError("Truncated Flight push")
        try:
            literal = json.loads(script[len(PUSH_PREFIX) : -1])
        except (ValueError, RecursionError) as err:
            raise TripPageParseError("Invalid Flight literal") from err
        if (
            isinstance(literal, list)
            and len(literal) == 2
            and literal[0] == 1
            and isinstance(literal[1], str)
        ):
            self.parts.append(literal[1])


def _model_records(stream: bytes) -> list[Any]:
    """Respect byte lengths of text records, including across push boundaries."""
    offset = 0
    records: dict[int, bytes] = {}
    models: list[Any] = []
    while offset < len(stream):
        if stream[offset : offset + 1] in (b"\n", b"\r"):
            offset += 1
            continue
        colon = stream.find(b":", offset)
        if colon == -1:
            raise TripPageParseError("Missing Flight record header")
        # The complete public page also emits anonymous preload hints (:HL).
        # They contain asset metadata, never timetable model data.
        if colon == offset and stream[colon + 1 : colon + 3] == b"HL":
            end = stream.find(b"\n", colon)
            if end == -1:
                raise TripPageParseError("Truncated Flight preload hint")
            offset = end
            continue
        try:
            record_id = int(stream[offset:colon], 16)
        except ValueError as err:
            raise TripPageParseError("Invalid Flight record ID") from err
        start = colon + 1
        if stream[start : start + 1] == b"T":
            comma = stream.find(b",", start)
            try:
                length = int(stream[start + 1 : comma], 16)
            except ValueError as err:
                raise TripPageParseError("Invalid Flight text length") from err
            if comma < 0 or length < 0 or comma + 1 + length > len(stream):
                raise TripPageParseError("Truncated Flight text record")
            end = comma + 1 + length
            body = stream[start:end]
        else:
            end = stream.find(b"\n", start)
            if end == -1:
                raise TripPageParseError("Truncated Flight model record")
            body = stream[start:end]
        if record_id in records and records[record_id] != body:
            raise TripPageParseError("Conflicting Flight record IDs")
        if len(records) >= MAX_RECORDS:
            raise TripPageParseError("Too many Flight records")
        records[record_id] = body
        if body[:1] in (b"{", b"["):
            try:
                models.append(json.loads(body))
            except (ValueError, RecursionError) as err:
                raise TripPageParseError("Invalid Flight model JSON") from err
        offset = end
    return models


def _trip_objects(models: list[Any]) -> list[dict[str, Any]]:
    """Ignore translation dictionaries; only structural trip objects qualify."""
    stack = [(item, 0) for item in models]
    found: list[dict[str, Any]] = []
    nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise TripPageParseError("Flight model traversal bound exceeded")
        if isinstance(value, dict):
            trip = value.get("trip")
            if isinstance(trip, dict) and isinstance(trip.get("id"), str):
                found.append(trip)
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
    return found


def parse_trip_page(html: str, trip_id: str) -> TripTimetable | None:
    """Return only the requested validated timetable; None means no trip object."""
    if len(html.encode("utf-8")) > TRIP_PAGE_MAX_BYTES:
        raise TripPageParseError("Trip page exceeds size bound")
    parser = _FlightScripts()
    parser.feed(html)
    parser.close()
    if parser.script is not None and parser.script.strip().startswith(PUSH_PREFIX):
        raise TripPageParseError("Unclosed Flight script")
    candidates = _trip_objects(_model_records("".join(parser.parts).encode("utf-8")))
    if not candidates:
        return None
    if len(candidates) != 1 or candidates[0]["id"] != trip_id:
        raise TripPageParseError("Unexpected trip identity")
    trip = candidates[0]

    # Only accepted fields are copied. Unverified realtime/vehicle fields are ignored.
    def optional(value: Any) -> Any:
        return None if value == "$undefined" else value

    try:
        departures = trip["departures"]
        if not isinstance(departures, list):
            raise TripPageParseError("Departures must be a list")
        cleaned = []
        for row in departures:
            item = {
                key: optional(row.get(key))
                for key in (
                    "stopId",
                    "name",
                    "order",
                    "scheduledDepartureUtc",
                    "canBoardDebark",
                )
            }
            if any(
                isinstance(value, str) and value.startswith("$")
                for value in item.values()
            ):
                raise TripPageParseError("Unresolved Flight reference")
            cleaned.append(item)
        return TripTimetable.model_validate(
            {
                "id": trip["id"],
                "headsign": optional(trip.get("headsign")),
                "departures": cleaned,
            }
        )
    except (KeyError, TypeError, AttributeError, ValueError, ValidationError) as err:
        raise TripPageParseError("Invalid trip timetable schema") from err
