"""Translink Queensland integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_MODE, DOMAIN, MODE_WINDOW
from .coordinator import TranslinkCoordinator
from .frontend import async_register_frontend
from .services import async_setup_services
from .window_coordinator import WindowCoordinator, window_store

_LOGGER = logging.getLogger(__name__)

type TranslinkConfigEntry = ConfigEntry[TranslinkCoordinator | WindowCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.DEVICE_TRACKER, Platform.EVENT]
WINDOW_PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.EVENT]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up shared dashboard assets and actions for all Translink entries."""
    async_setup_services(hass)
    await async_register_frontend(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TranslinkConfigEntry) -> bool:
    """Set up Translink from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    is_window = entry.data.get(CONF_MODE) == MODE_WINDOW
    coordinator = (
        WindowCoordinator(hass, entry)
        if is_window
        else TranslinkCoordinator(hass, entry)
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(
        entry, WINDOW_PLATFORMS if is_window else PLATFORMS
    )
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_update_options(
    hass: HomeAssistant, entry: TranslinkConfigEntry
) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TranslinkConfigEntry) -> bool:
    """Unload a config entry."""
    platforms = (
        WINDOW_PLATFORMS if entry.data.get(CONF_MODE) == MODE_WINDOW else PLATFORMS
    )
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        domain_data = hass.data.get(DOMAIN, {})
        coordinator: TranslinkCoordinator | WindowCoordinator | None = domain_data.pop(
            entry.entry_id, None
        ) or getattr(entry, "runtime_data", None)
        if coordinator is not None:
            await coordinator.async_shutdown()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: TranslinkConfigEntry) -> None:
    """Remove the persisted window ledger when the entry is deleted."""
    if entry.data.get(CONF_MODE) == MODE_WINDOW:
        await window_store(hass, entry.entry_id).async_remove()
