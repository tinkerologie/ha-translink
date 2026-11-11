"""Tests for Translink diagnostics module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.translink.client import JourneySummary
from custom_components.translink.const import DOMAIN
from custom_components.translink.diagnostics import async_get_config_entry_diagnostics


class FakeEntry:
    """Fake ConfigEntry."""

    def __init__(self) -> None:
        self.entry_id = "entry_1"
        self.data = {
            "start_name": "Central",
            "end_name": "Springfield",
            "origin_latitude": -27.466,
            "origin_longitude": 153.028,
        }
        self.options = {"scan_interval": 60}
        self.runtime_data = None


class FakeCoordinator:
    """Fake Coordinator."""

    def __init__(self) -> None:
        self.data = JourneySummary(
            status="on_time",
            duration_mins=41,
            origin_name="Central station",
            vehicle_latitude=-27.46,
            vehicle_longitude=153.03,
            destination_name="Springfield Central",
        )


@pytest.mark.asyncio
async def test_diagnostics_output() -> None:
    """Test diagnostics output contains redacted entry and coordinator data."""
    hass = MagicMock()
    entry = FakeEntry()
    coordinator = FakeCoordinator()
    entry.runtime_data = coordinator  # type: ignore[assignment]
    hass.data = {DOMAIN: {entry.entry_id: coordinator}}

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)  # type: ignore[arg-type]

    assert "entry" in diagnostics
    assert "options" in diagnostics
    assert "data" in diagnostics
    assert diagnostics["realtime_region"] == "SEQ"
    assert diagnostics["region_confirmed"] is False
    assert diagnostics["entry"]["start_name"] == "Central"
    assert diagnostics["entry"]["origin_latitude"] == "**REDACTED**"
    assert diagnostics["entry"]["origin_longitude"] == "**REDACTED**"
    assert diagnostics["data"]["duration_mins"] == 41
    assert diagnostics["data"]["status"] == "on_time"
    assert diagnostics["data"]["vehicle_latitude"] == "**REDACTED**"
    assert diagnostics["data"]["vehicle_longitude"] == "**REDACTED**"


async def test_notice_diagnostics_serializes_timestamps_and_scope() -> None:
    """Notice diagnostics serialize with no fabricated journey data."""
    from datetime import UTC, datetime

    from custom_components.translink.api.gtfs_realtime import AlertFeed
    from custom_components.translink.api.notices import build_notice_summary

    coordinator = MagicMock()
    coordinator.data = build_notice_summary(
        AlertFeed(None, "2.0", ()),
        "CNS",
        "network",
        None,
        datetime(2026, 11, 11, tzinfo=UTC),
    )
    entry = FakeEntry()
    entry.runtime_data = coordinator
    entry.data = {"mode": "notices", "notice_network": "CNS"}
    diagnostics = await async_get_config_entry_diagnostics(MagicMock(), entry)

    assert diagnostics["data"]["last_successful_fetch"] == "2026-11-11T00:00:00Z"
    assert diagnostics["data"]["network"] == "CNS"
    assert diagnostics["data"]["scope_type"] == "network"
    assert diagnostics["data"]["disruptions"] == []
    assert "stop_id" not in diagnostics["data"]
    assert "origin_name" not in diagnostics["data"]
