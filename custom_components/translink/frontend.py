"""Serve and register the bundled dashboard cards independently of entries."""

from __future__ import annotations

import hashlib
import logging
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from .const import CARD_FILENAME, CARD_URL

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
FRONTEND_PATH = Path(__file__).parent / "frontend" / CARD_FILENAME


def _bundle_hash() -> str:
    """Hash file contents off the event loop, including development rebuilds."""
    return hashlib.sha256(FRONTEND_PATH.read_bytes()).hexdigest()[:12]


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register once through integration async_setup; entities remain independent."""
    from homeassistant.components.http import StaticPathConfig
    from homeassistant.helpers.start import async_at_started

    try:
        digest = await hass.async_add_executor_job(_bundle_hash)
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(FRONTEND_PATH), cache_headers=True)]
        )
    except Exception:  # Optional UI must not prevent transit entity setup.
        _LOGGER.warning("Unable to serve Translink dashboard cards", exc_info=True)
        return

    async_at_started(
        hass, partial(_async_register_resource, url=f"{CARD_URL}?v={digest}")
    )


async def _async_register_resource(hass: HomeAssistant, *, url: str) -> None:
    """Isolate HA's internal Lovelace collection API and touch only our resource."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    try:
        lovelace = hass.data.get(LOVELACE_DATA)
        resources = lovelace.resources if lovelace is not None else None
        if not isinstance(resources, ResourceStorageCollection):
            _LOGGER.info(
                "Lovelace storage resources unavailable; add %s as a module resource "
                "in your YAML dashboard configuration",
                url,
            )
            return

        await resources.async_get_info()
        own = [
            item
            for item in resources.async_items()
            if urlsplit(item["url"]).path == CARD_URL
            and not urlsplit(item["url"]).netloc
        ]
        if not own:
            await resources.async_create_item({"url": url, "res_type": "module"})
            return
        keep, *duplicates = own
        if keep["url"] != url or keep["type"] != "module":
            await resources.async_update_item(
                keep["id"], {"url": url, "res_type": "module"}
            )
        for duplicate in duplicates:
            await resources.async_delete_item(duplicate["id"])
    except Exception:  # Resource failures must not make transit entities unavailable.
        _LOGGER.warning(
            "Unable to register Translink dashboard resource", exc_info=True
        )
