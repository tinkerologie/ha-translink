"""Tests for the scoped service notice contract."""

from datetime import UTC, datetime

from custom_components.translink.api.gtfs_realtime import (
    AlertDetail,
    AlertFeed,
    AlertPeriod,
    AlertSelector,
)

NOW = datetime(2026, 11, 11, tzinfo=UTC)
SECOND = int(NOW.timestamp())


def _feed(*alerts: AlertDetail) -> AlertFeed:
    return AlertFeed(SECOND - 20, "2.0", alerts)


def test_route_notices_keep_network_alerts_and_match_complete_route_ids() -> None:
    """Scoped alerts include a matching selector or an agency-wide selector."""
    from custom_components.translink.api.notices import build_notice_summary

    alerts = _feed(
        AlertDetail("agency", selectors=(AlertSelector(agency_id="QR"),)),
        AlertDetail(
            "route",
            selectors=(
                AlertSelector(route_id="other", route_type=3),
                AlertSelector(route_id="RPSP-5154", stop_id="600029"),
            ),
        ),
        AlertDetail(
            "trip-route", selectors=(AlertSelector(trip_id="T", trip_route_id="RPSP"),)
        ),
        AlertDetail("stop", selectors=(AlertSelector(stop_id="600029"),)),
        AlertDetail("trip", selectors=(AlertSelector(trip_id="T"),)),
        AlertDetail(
            "unknown",
            selectors=(AlertSelector(agency_id="QR", has_unknown_fields=True),),
        ),
        AlertDetail("unspecified"),
    )
    summary = build_notice_summary(alerts, "SEQ", "route", "RPSP", NOW)
    assert [row["id"] for row in summary.disruptions] == [
        "agency",
        "route",
        "trip-route",
    ]
    assert [row["match"] for row in summary.disruptions] == [
        "network",
        "route",
        "route",
    ]
    assert [
        selector["scope"] for selector in summary.disruptions[1]["informed_entities"]
    ] == ["route", "stop"]
    assert summary.disruptions[1]["route"] is None
    assert summary.unclassified_count == 2
    for route in ("RP", "RPSP-5153"):
        assert [
            row["id"]
            for row in build_notice_summary(
                alerts, "SEQ", "route", route, NOW
            ).disruptions
        ] == ["agency"]


def test_mode_notices_use_explicit_types_and_keep_agency_wide_notices() -> None:
    """Route IDs and unknown selectors supply no transport mode by themselves."""
    from custom_components.translink.api.notices import build_notice_summary

    alerts = _feed(
        AlertDetail("network", selectors=(AlertSelector(agency_id="QR"),)),
        AlertDetail("route", selectors=(AlertSelector(route_id="RPSP"),)),
        AlertDetail("train", selectors=(AlertSelector(route_type=2, route_id="RPSP"),)),
        AlertDetail("bus", selectors=(AlertSelector(route_type=3),)),
        AlertDetail("unknown"),
    )
    summary = build_notice_summary(alerts, "CNS", "mode", 2, NOW)
    assert [row["id"] for row in summary.disruptions] == ["network", "train"]
    assert summary.disruptions[-1]["informed_entities"][0]["mode"] == "Train"
    assert summary.unclassified_count == 2


def test_network_notices_order_windows_deduplicate_and_bound_output() -> None:
    """A scoped summary keeps useful data after sorting and capping."""
    from custom_components.translink.api.notices import build_notice_summary
    from custom_components.translink.const import (
        NOTICE_DESCRIPTION_LIMIT,
        NOTICE_LIMIT,
        NOTICE_PERIOD_LIMIT,
        NOTICE_SELECTOR_LIMIT,
    )

    active = AlertDetail(
        "active",
        "First title",
        description_text="x" * (NOTICE_DESCRIPTION_LIMIT + 1),
        periods=(AlertPeriod(SECOND - 1, SECOND), AlertPeriod(end=SECOND + 2))
        + (AlertPeriod(start=SECOND + 200),) * NOTICE_PERIOD_LIMIT,
        selectors=(AlertSelector(),) * (NOTICE_SELECTOR_LIMIT + 1),
    )
    duplicate = AlertDetail("active", "Duplicate title")
    future = AlertDetail("future", periods=(AlertPeriod(start=SECOND + 30),))
    sooner = AlertDetail(
        "sooner", periods=(AlertPeriod(SECOND, SECOND), AlertPeriod(start=SECOND + 10))
    )
    expired = AlertDetail("expired", periods=(AlertPeriod(end=SECOND),))
    anonymous = AlertDetail(
        header_text="Anonymous", periods=(AlertPeriod(start=SECOND + 20),)
    )
    later = tuple(
        AlertDetail(f"later-{i}", periods=(AlertPeriod(start=SECOND + 40),))
        for i in range(NOTICE_LIMIT)
    )
    alerts = _feed(
        future, sooner, expired, active, duplicate, anonymous, anonymous, *later
    )
    summary = build_notice_summary(alerts, "SEQ", "network", None, NOW)

    rows = summary.disruptions
    assert [row["id"] for row in rows[:2]] == ["active", "sooner"]
    assert rows[2]["id"].startswith("anon-")
    assert rows[3]["id"] == "future"
    assert rows[0]["title"] == "First title"
    assert rows[0]["status"] == "active"
    assert rows[0]["match"] == "unknown"
    assert rows[0]["starts_utc"] is None
    assert rows[0]["ends_utc"] == "2026-11-11T00:00:02+00:00"
    assert len(rows[0]["description"]) == NOTICE_DESCRIPTION_LIMIT
    assert len(rows[0]["active_periods"]) == NOTICE_PERIOD_LIMIT
    assert rows[0]["active_periods_omitted"] == 2
    assert len(rows[0]["informed_entities"]) == NOTICE_SELECTOR_LIMIT
    assert rows[0]["informed_entities_omitted"] == 1
    assert rows[1]["status"] == "upcoming"
    assert summary.total_count == summary.disruptions_count == NOTICE_LIMIT + 4
    assert summary.shown_count == NOTICE_LIMIT
    assert summary.active_count == 1
    assert summary.upcoming_count == NOTICE_LIMIT + 3
    assert summary.duplicates_dropped == 2
    assert summary.last_successful_fetch == NOW
    assert summary.model_dump(mode="json")["feed_timestamp"] == "2026-11-10T23:59:40Z"


def test_notice_cap_keeps_current_period_when_earlier_feed_periods_are_expired() -> (
    None
):
    """The cap retains the only current window even if it occurs later in the feed."""
    from custom_components.translink.api.notices import build_notice_summary
    from custom_components.translink.const import NOTICE_PERIOD_LIMIT

    periods = (AlertPeriod(end=SECOND),) * NOTICE_PERIOD_LIMIT + (
        AlertPeriod(start=SECOND),
    )
    summary = build_notice_summary(
        _feed(AlertDetail("id", periods=periods)), "SEQ", "network", None, NOW
    )
    row = summary.disruptions[0]
    assert row["active_periods"][-1] == {"start": NOW.isoformat(), "end": None}
    assert row["active_periods_omitted"] == 1
