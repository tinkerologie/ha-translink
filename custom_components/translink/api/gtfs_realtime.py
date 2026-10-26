"""Lightweight pure-Python GTFS-Realtime Protobuf parser for Translink."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class VehiclePositionRecord:
    """Realtime vehicle position."""

    entity_id: str
    vehicle_id: str | None
    vehicle_label: str | None
    trip_id: str | None
    route_id: str | None
    latitude: float
    longitude: float
    bearing: float | None = None
    speed: float | None = None
    timestamp: int | None = None


@dataclass(slots=True)
class StopTimeEventRecord:
    """An explicitly supplied GTFS-RT prediction; absent is distinct from zero."""

    time: int | None = None
    delay: int | None = None
    uncertainty: int | None = None


@dataclass(slots=True)
class StopTimeUpdateRecord:
    """One visit to a stop, retained in feed order, including repeated visits."""

    stop_sequence: int | None = None
    stop_id: str | None = None
    schedule_relationship: int | None = None
    arrival: StopTimeEventRecord | None = None
    departure: StopTimeEventRecord | None = None


@dataclass(slots=True)
class TripUpdateRecord:
    """Realtime trip update with delay and stop updates."""

    entity_id: str
    trip_id: str | None
    route_id: str | None
    delay_seconds: int = 0
    stop_id: str | None = None
    timestamp: int | None = None
    start_date: str | None = None
    start_time: str | None = None
    trip_schedule_relationship: int | None = None
    stop_time_updates: tuple[StopTimeUpdateRecord, ...] = ()


@dataclass(slots=True)
class AlertRecord:
    """Realtime service alert."""

    entity_id: str
    header_text: str
    description_text: str | None = None
    route_ids: tuple[str, ...] = ()
    stop_ids: tuple[str, ...] = ()


def _parse_varint(data: bytes, offset: int) -> tuple[int, int]:
    """Parse a variable-length integer (varint) from binary data."""
    res = 0
    shift = 0
    data_len = len(data)
    while offset < data_len:
        b = data[offset]
        offset += 1
        res |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return res, offset


def _parse_fields(
    data: bytes, offset: int = 0, limit: int | None = None
) -> list[tuple[int, int, Any]]:
    """Parse protobuf fields into (field_number, wire_type, raw_value)."""
    if limit is None:
        limit = len(data)
    fields: list[tuple[int, int, Any]] = []
    val: Any
    while offset < limit:
        tag, offset = _parse_varint(data, offset)
        field_num = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:  # Varint
            val, offset = _parse_varint(data, offset)
            fields.append((field_num, wire_type, val))
        elif wire_type == 1:  # 64-bit
            if offset + 8 > limit:
                break
            val = struct.unpack("<Q", data[offset : offset + 8])[0]
            offset += 8
            fields.append((field_num, wire_type, val))
        elif wire_type == 2:  # Length-delimited (string / bytes / submessage)
            length, offset = _parse_varint(data, offset)
            if offset + length > limit:
                break
            val = data[offset : offset + length]
            offset += length
            fields.append((field_num, wire_type, val))
        elif wire_type == 5:  # 32-bit float / fixed32
            if offset + 4 > limit:
                break
            val = struct.unpack("<f", data[offset : offset + 4])[0]
            offset += 4
            fields.append((field_num, wire_type, val))
        else:
            # Skip unsupported wire type or stop
            break
    return fields


def _to_int32(val: int) -> int:
    """Convert protobuf varint to signed 32-bit integer."""
    v = val & 0xFFFFFFFF
    return v if v < 0x80000000 else v - 0x100000000


def _decode_string(val: Any) -> str:
    """Safely decode binary data to string."""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val)


def _decode_translated_string(data: bytes) -> str:
    """Extract plain text from a GTFS-RT TranslatedString message."""
    fields = _parse_fields(data)
    for field_num, _, val in fields:
        if field_num == 1 and isinstance(val, bytes):  # Translation
            trans_fields = _parse_fields(val)
            for t_num, _, t_val in trans_fields:
                if t_num == 1:  # text
                    return _decode_string(t_val)
    return ""


def extract_base_trip_id(trip_id: str | None) -> str | None:
    """Extract normalized base trip ID for cross-feed correlation.

    Translink Journey Planner returns trip IDs such as 's_T_SPRP_9_20261008_39040630'
    where the final segment is the base GTFS trip ID. GTFS-RT feeds provide trip IDs
    such as '39040630-QR 26_27-44171-DY37' where the prefix before the hyphen is the
    base GTFS trip ID.
    """
    if not trip_id:
        return None
    base = trip_id.split("-")[0].strip()
    if "_" in base:
        parts = base.split("_")
        base = parts[-1].strip()
    return base or None


def parse_vehicle_positions(raw_bytes: bytes) -> dict[str, VehiclePositionRecord]:
    """Parse GTFS-RT VehiclePositions binary payload into a lookup dict."""
    result: dict[str, VehiclePositionRecord] = {}
    top_fields = _parse_fields(raw_bytes)
    for field_num, _, ent_bytes in top_fields:
        if field_num != 2 or not isinstance(ent_bytes, bytes):
            continue

        ent_fields = _parse_fields(ent_bytes)
        entity_id = ""
        veh_bytes: bytes | None = None

        for ef_num, _, ef_val in ent_fields:
            if ef_num == 1:
                entity_id = _decode_string(ef_val)
            elif ef_num == 4 and isinstance(ef_val, bytes):
                veh_bytes = ef_val

        if not veh_bytes:
            continue

        v_fields = _parse_fields(veh_bytes)
        trip_id: str | None = None
        route_id: str | None = None
        veh_id: str | None = None
        veh_label: str | None = None
        lat: float | None = None
        lng: float | None = None
        bearing: float | None = None
        speed: float | None = None
        timestamp: int | None = None

        for vf_num, _, vf_val in v_fields:
            if vf_num == 1 and isinstance(vf_val, bytes):  # TripDescriptor
                trip_fields = _parse_fields(vf_val)
                for tf_num, _, tf_val in trip_fields:
                    if tf_num == 1:
                        trip_id = _decode_string(tf_val)
                    elif tf_num == 5:
                        route_id = _decode_string(tf_val)
            elif vf_num == 2 and isinstance(vf_val, bytes):  # Position
                pos_fields = _parse_fields(vf_val)
                for pf_num, _, pf_val in pos_fields:
                    if pf_num == 1 and isinstance(pf_val, (float, int)):
                        lat = float(pf_val)
                    elif pf_num == 2 and isinstance(pf_val, (float, int)):
                        lng = float(pf_val)
                    elif pf_num == 3 and isinstance(pf_val, (float, int)):
                        bearing = float(pf_val)
                    elif pf_num == 5 and isinstance(pf_val, (float, int)):
                        speed = float(pf_val)
            elif vf_num == 5 and isinstance(vf_val, int):
                timestamp = vf_val
            elif vf_num == 8 and isinstance(vf_val, bytes):  # VehicleDescriptor
                vd_fields = _parse_fields(vf_val)
                for vdf_num, _, vdf_val in vd_fields:
                    if vdf_num == 1:
                        veh_id = _decode_string(vdf_val)
                    elif vdf_num == 2:
                        veh_label = _decode_string(vdf_val)

        if lat is not None and lng is not None:
            record = VehiclePositionRecord(
                entity_id=entity_id,
                vehicle_id=veh_id,
                vehicle_label=veh_label,
                trip_id=trip_id,
                route_id=route_id,
                latitude=round(lat, 6),
                longitude=round(lng, 6),
                bearing=round(bearing, 1) if bearing is not None else None,
                speed=round(speed, 2) if speed is not None else None,
                timestamp=timestamp,
            )
            if trip_id:
                result[trip_id] = record
                base_id = extract_base_trip_id(trip_id)
                if base_id and base_id not in result:
                    result[base_id] = record
            if veh_id:
                result[veh_id] = record
            result[entity_id] = record

    return result


def _parse_stop_event(data: bytes) -> StopTimeEventRecord:
    """Decode only explicit event values without defaulting missing delay to zero."""
    result = StopTimeEventRecord()
    for field, wire, value in _parse_fields(data):
        if wire != 0:
            continue
        if field == 1:
            result.delay = _to_int32(value)
        elif field == 2:
            result.time = value
        elif field == 3:
            result.uncertainty = value
    return result


def _parse_stop_update(data: bytes) -> StopTimeUpdateRecord:
    """Preserve a stop visit and its arrival/departure predictions."""
    result = StopTimeUpdateRecord()
    for field, wire, value in _parse_fields(data):
        if field == 1 and wire == 0:
            result.stop_sequence = value
        elif field == 4 and wire == 2:
            result.stop_id = _decode_string(value)
        elif field == 5 and wire == 0:
            result.schedule_relationship = value
        elif field == 2 and wire == 2:
            result.arrival = _parse_stop_event(value)
        elif field == 3 and wire == 2:
            result.departure = _parse_stop_event(value)
    return result


def parse_trip_updates(raw_bytes: bytes) -> dict[str, TripUpdateRecord]:
    """Parse GTFS-RT TripUpdates binary payload into a lookup dict."""
    result: dict[str, TripUpdateRecord] = {}
    top_fields = _parse_fields(raw_bytes)
    for field_num, _, ent_bytes in top_fields:
        if field_num != 2 or not isinstance(ent_bytes, bytes):
            continue

        ent_fields = _parse_fields(ent_bytes)
        entity_id = ""
        tu_bytes: bytes | None = None

        for ef_num, _, ef_val in ent_fields:
            if ef_num == 1:
                entity_id = _decode_string(ef_val)
            elif ef_num == 3 and isinstance(ef_val, bytes):
                tu_bytes = ef_val

        if not tu_bytes:
            continue

        tu_fields = _parse_fields(tu_bytes)
        trip_id: str | None = None
        route_id: str | None = None
        delay_sec = 0
        last_stop_id: str | None = None
        timestamp: int | None = None
        start_date: str | None = None
        start_time: str | None = None
        relationship: int | None = None
        stop_updates: list[StopTimeUpdateRecord] = []

        for tuf_num, _, tuf_val in tu_fields:
            if tuf_num == 1 and isinstance(tuf_val, bytes):  # TripDescriptor
                trip_fields = _parse_fields(tuf_val)
                for tf_num, _, tf_val in trip_fields:
                    if tf_num == 1:
                        trip_id = _decode_string(tf_val)
                    elif tf_num == 5:
                        route_id = _decode_string(tf_val)
                    elif tf_num == 2:
                        start_time = _decode_string(tf_val)
                    elif tf_num == 3:
                        start_date = _decode_string(tf_val)
                    elif tf_num == 4 and isinstance(tf_val, int):
                        relationship = tf_val
            elif tuf_num == 2 and isinstance(tuf_val, bytes):  # StopTimeUpdate
                stop_updates.append(_parse_stop_update(tuf_val))
                stu_fields = _parse_fields(tuf_val)
                for stuf_num, _, stuf_val in stu_fields:
                    if stuf_num == 4:
                        last_stop_id = _decode_string(stuf_val)
                    elif stuf_num in (2, 3) and isinstance(
                        stuf_val, bytes
                    ):  # arrival/departure
                        ste_fields = _parse_fields(stuf_val)
                        for stef_num, _, stef_val in ste_fields:
                            if stef_num == 1 and isinstance(stef_val, int):
                                delay_sec = _to_int32(stef_val)
            elif tuf_num == 4 and isinstance(tuf_val, int):
                timestamp = tuf_val
            elif tuf_num == 5 and isinstance(tuf_val, int):
                delay_sec = _to_int32(tuf_val)

        record = TripUpdateRecord(
            entity_id=entity_id,
            trip_id=trip_id,
            route_id=route_id,
            delay_seconds=delay_sec,
            stop_id=last_stop_id,
            timestamp=timestamp,
            start_date=start_date,
            start_time=start_time,
            trip_schedule_relationship=relationship,
            stop_time_updates=tuple(stop_updates),
        )
        if trip_id:
            result[trip_id] = record
            base_id = extract_base_trip_id(trip_id)
            if base_id and base_id not in result:
                result[base_id] = record
        result[entity_id] = record

    return result


def parse_alerts(raw_bytes: bytes) -> list[AlertRecord]:
    """Parse GTFS-RT Alerts binary payload into a list of AlertRecord objects."""
    result: list[AlertRecord] = []
    top_fields = _parse_fields(raw_bytes)
    for field_num, _, ent_bytes in top_fields:
        if field_num != 2 or not isinstance(ent_bytes, bytes):
            continue

        ent_fields = _parse_fields(ent_bytes)
        entity_id = ""
        alert_bytes: bytes | None = None

        for ef_num, _, ef_val in ent_fields:
            if ef_num == 1:
                entity_id = _decode_string(ef_val)
            elif ef_num == 5 and isinstance(ef_val, bytes):
                alert_bytes = ef_val

        if not alert_bytes:
            continue

        a_fields = _parse_fields(alert_bytes)
        header_text = ""
        desc_text: str | None = None
        route_ids: list[str] = []
        stop_ids: list[str] = []

        for af_num, _, af_val in a_fields:
            if af_num == 5 and isinstance(af_val, bytes):  # EntitySelector
                es_fields = _parse_fields(af_val)
                for esf_num, _, esf_val in es_fields:
                    if esf_num == 2:  # route_id
                        route_ids.append(_decode_string(esf_val))
                    elif esf_num == 5:  # stop_id
                        stop_ids.append(_decode_string(esf_val))
            elif af_num == 10 and isinstance(af_val, bytes):  # header_text
                header_text = _decode_translated_string(af_val)
            elif af_num == 11 and isinstance(af_val, bytes):  # description_text
                desc_text = _decode_translated_string(af_val)

        if header_text or desc_text:
            result.append(
                AlertRecord(
                    entity_id=entity_id,
                    header_text=header_text
                    or (desc_text[:100] if desc_text else "Alert"),
                    description_text=desc_text,
                    route_ids=tuple(route_ids),
                    stop_ids=tuple(stop_ids),
                )
            )

    return result
