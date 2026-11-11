"""Scope and bound alerts from a single Translink regional feed."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Literal

from ..const import (
    NOTICE_DESCRIPTION_LIMIT,
    NOTICE_LIMIT,
    NOTICE_PERIOD_LIMIT,
    NOTICE_ROUTE_TYPES,
    NOTICE_SELECTOR_LIMIT,
)
from .gtfs_realtime import AlertDetail, AlertFeed, AlertPeriod, AlertSelector
from .models import NoticeSummary

NoticeScope = Literal["network", "route", "mode"]
SelectorScope = Literal["network", "mode", "route", "stop", "trip", "unknown"]
_NOTICE_MODES = {route_type: mode for mode, route_type in NOTICE_ROUTE_TYPES.items()}
_MAX_TIMESTAMP = 253402300799  # 9999-12-31T23:59:59Z


def _timestamp(value: int | None) -> datetime | None:
    if value is None or value > _MAX_TIMESTAMP:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def _iso(value: int | None) -> str | None:
    timestamp = _timestamp(value)
    return timestamp.isoformat() if timestamp is not None else None


def _scope(selector: AlertSelector) -> SelectorScope:
    if selector.trip_id:
        return "trip"
    if selector.stop_id:
        return "stop"
    if selector.route_id or selector.trip_route_id:
        return "route"
    if selector.route_type is not None:
        return "mode"
    if (
        selector.agency_id
        and selector.direction_id is None
        and not selector.has_unknown_fields
    ):
        return "network"
    return "unknown"


def _route_matches(feed_id: str, wanted_id: str) -> bool:
    if feed_id == wanted_id:
        return True
    base, _, version = feed_id.rpartition("-")
    return base == wanted_id and version.isascii() and version.isdecimal()


def _selector_matches_route(selector: AlertSelector, route_id: str) -> bool:
    route_ids = tuple(
        value for value in (selector.route_id, selector.trip_route_id) if value
    )
    return any(_route_matches(value, route_id) for value in route_ids)


def _match(
    selectors: tuple[AlertSelector, ...], scope: NoticeScope, value: str | int | None
) -> tuple[SelectorScope | None, bool]:
    scopes = tuple(_scope(selector) for selector in selectors)
    classified = next((kind for kind in scopes if kind != "unknown"), None)
    if scope == "network":
        return (
            "network" if "network" in scopes else classified or "unknown"
        ), classified is None
    if "network" in scopes:
        return "network", False
    if scope == "route":
        if isinstance(value, str) and any(
            _selector_matches_route(selector, value) for selector in selectors
        ):
            return "route", False
        return None, classified is None
    if isinstance(value, int) and any(
        selector.route_type == value for selector in selectors
    ):
        return "mode", False
    return None, (
        not scopes
        or "unknown" in scopes
        or any(
            selector.route_type is None
            and (selector.route_id or selector.trip_route_id)
            for selector in selectors
        )
    )


def _current_or_next_period(
    periods: tuple[AlertPeriod, ...], now: float
) -> tuple[Literal["active", "upcoming", "expired"], AlertPeriod]:
    if not periods:
        return "active", AlertPeriod()
    upcoming: list[AlertPeriod] = []
    for period in periods:
        if period.end is not None and (
            period.end <= now
            or (period.start is not None and period.end <= period.start)
        ):
            continue
        if period.start is None or period.start <= now:
            return "active", period
        upcoming.append(period)
    if upcoming:
        return "upcoming", min(upcoming, key=lambda period: period.start or 0)
    return "expired", AlertPeriod()


def _notice_id(alert: AlertDetail) -> str:
    if alert.entity_id:
        return alert.entity_id
    content = json.dumps(
        (
            alert.header_text,
            alert.description_text,
            [asdict(selector) for selector in alert.selectors],
        ),
        sort_keys=True,
    ).encode()
    return f"anon-{hashlib.sha256(content).hexdigest()[:24]}"


def _notice_row(
    alert: AlertDetail,
    alert_id: str,
    status: Literal["active", "upcoming"],
    match: SelectorScope,
    primary: AlertPeriod,
) -> dict[str, Any]:
    description = alert.description_text
    periods = alert.periods[:NOTICE_PERIOD_LIMIT]
    if periods and primary not in periods:
        periods = (*periods[:-1], primary)
    selectors = alert.selectors[:NOTICE_SELECTOR_LIMIT]
    return {
        "id": alert_id,
        "title": (alert.header_text or description or "Service Notice")[:255],
        "description": description[:NOTICE_DESCRIPTION_LIMIT] if description else None,
        "cause": alert.cause,
        "effect": alert.effect,
        "severity": alert.severity,
        "starts_utc": _iso(primary.start),
        "ends_utc": _iso(primary.end),
        "route": None,
        "leg": None,
        "status": status,
        "match": match,
        "active_periods": [
            {"start": _iso(period.start), "end": _iso(period.end)} for period in periods
        ],
        "active_periods_omitted": len(alert.periods) - len(periods),
        "informed_entities": [
            {
                **asdict(selector),
                "scope": _scope(selector),
                "mode": _NOTICE_MODES.get(selector.route_type)
                if selector.route_type is not None
                else None,
            }
            for selector in selectors
        ],
        "informed_entities_omitted": len(alert.selectors) - len(selectors),
    }


def build_notice_summary(
    feed: AlertFeed,
    network: str,
    scope: NoticeScope,
    value: str | int | None,
    now: datetime,
) -> NoticeSummary:
    """Keep matching active and upcoming alerts, in status and feed order."""
    ids: set[str] = set()
    duplicates_dropped = unclassified_count = 0
    active: list[tuple[AlertDetail, str, SelectorScope, AlertPeriod]] = []
    upcoming: list[tuple[AlertDetail, str, SelectorScope, AlertPeriod]] = []
    now_timestamp = now.timestamp()
    for alert in feed.alerts:
        alert_id = _notice_id(alert)
        if alert_id in ids:
            duplicates_dropped += 1
            continue
        ids.add(alert_id)
        status, primary = _current_or_next_period(alert.periods, now_timestamp)
        if status == "expired":
            continue
        match, unclassified = _match(alert.selectors, scope, value)
        unclassified_count += unclassified
        if match is not None:
            (active if status == "active" else upcoming).append(
                (alert, alert_id, match, primary)
            )

    upcoming.sort(key=lambda item: item[3].start or 0)
    total_count = len(active) + len(upcoming)
    rows = [
        _notice_row(alert, alert_id, "active", match, primary)
        for alert, alert_id, match, primary in active[:NOTICE_LIMIT]
    ]
    rows.extend(
        _notice_row(alert, alert_id, "upcoming", match, primary)
        for alert, alert_id, match, primary in upcoming[: NOTICE_LIMIT - len(rows)]
    )
    first = rows[0] if rows else {}
    return NoticeSummary(
        network=network,
        scope_type=scope,
        scope_value=value,
        feed_timestamp=_timestamp(feed.header_timestamp),
        last_successful_fetch=now,
        last_updated=now,
        total_count=total_count,
        shown_count=len(rows),
        active_count=len(active),
        upcoming_count=len(upcoming),
        unclassified_count=unclassified_count,
        duplicates_dropped=duplicates_dropped,
        disruptions_count=total_count,
        disruptions=rows,
        disruptions_description=first.get("description")
        or first.get("title")
        or "No service notices",
        disruptions_summary=f"{len(active)} active, {len(upcoming)} upcoming"
        if total_count
        else "Normal",
        latest_disruption_title=first.get("title"),
        latest_disruption_description=first.get("description"),
    )
