"""Verify card resources using Home Assistant's real HTTP and Lovelace APIs."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceYAMLCollection
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.translink import async_setup
from custom_components.translink.const import CARD_URL
from custom_components.translink.frontend import (
    FRONTEND_PATH,
    _async_register_resource,
    _bundle_hash,
    async_register_frontend,
)


@pytest.fixture
async def resources(hass: HomeAssistant):
    """Load the actual storage resource collection, not a simulated seam."""
    assert await async_setup_component(
        hass, "lovelace", {"lovelace": {"mode": "storage"}}
    )
    collection = hass.data[LOVELACE_DATA].resources
    await collection.async_get_info()
    return collection


async def test_resource_create_update_deduplicate(
    hass: HomeAssistant, resources
) -> None:
    """Update in place and collapse only duplicates of our own relative URL."""
    unrelated = await resources.async_create_item(
        {"url": "/globird/cards.js", "res_type": "module"}
    )
    external = await resources.async_create_item(
        {"url": f"https://example.com{CARD_URL}", "res_type": "module"}
    )
    first = await resources.async_create_item(
        {"url": f"{CARD_URL}?v=old", "res_type": "js"}
    )
    await resources.async_create_item(
        {"url": f"{CARD_URL}?v=duplicate", "res_type": "module"}
    )
    await _async_register_resource(hass, url=f"{CARD_URL}?v=new")
    await _async_register_resource(hass, url=f"{CARD_URL}?v=new")
    items = resources.async_items()
    assert len(items) == 3
    assert unrelated in items
    assert external in items
    own = next(item for item in items if item["id"] == first["id"])
    assert own["url"] == f"{CARD_URL}?v=new"
    assert own["type"] == "module"


async def test_create_resource(hass: HomeAssistant, resources) -> None:
    """Create a single module and keep it stable across repeated calls."""
    await _async_register_resource(hass, url=f"{CARD_URL}?v=test")
    await _async_register_resource(hass, url=f"{CARD_URL}?v=test")
    assert len(resources.async_items()) == 1
    assert resources.async_items()[0]["type"] == "module"


async def test_static_bundle_served(
    hass: HomeAssistant, hass_client, resources
) -> None:
    """The packaged JavaScript is actually served by HA's HTTP server."""
    assert FRONTEND_PATH.is_file()
    assert len(_bundle_hash()) == 12
    assert await async_setup(hass, {})
    client = await hass_client()
    response = await client.get(CARD_URL)
    assert response.status == 200
    assert await response.read() == FRONTEND_PATH.read_bytes()
    await hass.async_start()
    await hass.async_block_till_done()
    own = [item for item in resources.async_items() if item["url"].startswith(CARD_URL)]
    assert len(own) == 1
    assert own[0]["url"] == f"{CARD_URL}?v={_bundle_hash()}"


async def test_missing_and_yaml_resources(hass: HomeAssistant, resources) -> None:
    """YAML collections and absent Lovelace are left unchanged."""
    lovelace = hass.data.pop(LOVELACE_DATA)
    await _async_register_resource(hass, url=CARD_URL)
    yaml_resources = ResourceYAMLCollection([{"url": "/other.js", "type": "module"}])
    lovelace.resources = yaml_resources
    hass.data[LOVELACE_DATA] = lovelace
    await _async_register_resource(hass, url=CARD_URL)
    assert yaml_resources.async_items() == [{"url": "/other.js", "type": "module"}]


async def test_optional_registration_failures(hass: HomeAssistant, resources) -> None:
    """Optional asset/resource failures do not fail integration setup."""
    with patch(
        "custom_components.translink.frontend._bundle_hash", side_effect=OSError
    ):
        assert await async_setup(hass, {})
    with patch.object(resources, "async_get_info", side_effect=RuntimeError):
        await _async_register_resource(hass, url=CARD_URL)
    with (
        patch.object(
            hass.http,
            "async_register_static_paths",
            new=AsyncMock(side_effect=RuntimeError),
        ),
        patch("homeassistant.helpers.start.async_at_started") as callback,
    ):
        await async_register_frontend(hass)
        callback.assert_not_called()
