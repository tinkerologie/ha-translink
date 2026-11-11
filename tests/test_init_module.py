"""Tests for Translink __init__ setup and unload handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import MockConfigEntry

from custom_components.translink import (
    PLATFORMS,
    async_setup_entry,
    async_unload_entry,
    async_update_options,
)
from custom_components.translink.const import CONF_MODE, DOMAIN, MODE_JOURNEY


async def test_async_setup_entry_success(hass: HomeAssistant) -> None:
    """Test successful setup of entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_MODE: MODE_JOURNEY},
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.translink.coordinator.async_get_clientsession"),
        patch(
            "custom_components.translink.coordinator.TranslinkCoordinator.async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            return_value=True,
        ) as mock_forward,
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True
    assert entry.runtime_data is not None
    assert hass.data[DOMAIN][entry.entry_id] == entry.runtime_data
    mock_forward.assert_awaited_once_with(entry, PLATFORMS)


async def test_async_update_options(hass: HomeAssistant) -> None:
    """Test update options triggers entry reload."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_MODE: MODE_JOURNEY},
    )
    entry.add_to_hass(hass)

    with patch.object(hass.config_entries, "async_reload") as mock_reload:
        await async_update_options(hass, entry)
        mock_reload.assert_awaited_once_with(entry.entry_id)


async def test_async_unload_entry_success(hass: HomeAssistant) -> None:
    """Test successful unload of entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_MODE: MODE_JOURNEY},
    )
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.async_shutdown = AsyncMock()
    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=True,
    ):
        result = await async_unload_entry(hass, entry)

    assert result is True
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_async_unload_entry_failure(hass: HomeAssistant) -> None:
    """Test failed unload leaves runtime data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_MODE: MODE_JOURNEY},
    )
    entry.add_to_hass(hass)
    entry.runtime_data = MagicMock()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.runtime_data

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=False,
    ):
        result = await async_unload_entry(hass, entry)

    assert result is False
    assert entry.entry_id in hass.data[DOMAIN]


def test_icons_json_validity() -> None:
    """Test that icons.json loads and contains correct platform icon."""
    import json
    from pathlib import Path

    icons_file = (
        Path(__file__).parent.parent / "custom_components" / "translink" / "icons.json"
    )
    assert icons_file.is_file()

    with icons_file.open() as fp:
        icons_data = json.load(fp)

    sensor_icons = icons_data.get("entity", {}).get("sensor", {})
    assert sensor_icons.get("platform", {}).get("default") == "mdi:bus-stop-uncovered"


def test_english_translations_match_config_flow_strings() -> None:
    """English translations include all integration string keys and values."""
    import json
    from pathlib import Path

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            assert key not in result, f"Duplicate translation key: {key}"
            result[key] = value
        return result

    component = Path(__file__).parents[1] / "custom_components" / "translink"
    assert json.loads(
        (component / "strings.json").read_text(), object_pairs_hook=unique_object
    ) == json.loads(
        (component / "translations" / "en.json").read_text(),
        object_pairs_hook=unique_object,
    )


async def test_removing_non_window_entry_leaves_window_store_untouched(
    hass: HomeAssistant,
) -> None:
    """Journey and stop removal have no commute ledger side effect."""
    from custom_components.translink import async_remove_entry

    entry = MockConfigEntry(domain=DOMAIN)
    with patch("custom_components.translink.window_store") as store:
        await async_remove_entry(hass, entry)
    store.assert_not_called()
