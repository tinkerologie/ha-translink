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
