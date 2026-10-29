"""Common fixtures and test helpers for Translink tests."""

from __future__ import annotations

import json
import sys
import types
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

# Installed before anything imports the integration, so reports logged while
# pytest imports the test modules are caught too.
from tests.deprecations import HANDLER as DEPRECATION_REPORTS
from tests.deprecations import install_deprecation_report_handler

if TYPE_CHECKING:
    from collections.abc import Generator

install_deprecation_report_handler()

FIXTURES_DIR = Path(__file__).parent / "fixtures"

if "voluptuous" not in sys.modules:
    vol = types.ModuleType("voluptuous")

    class Schema(dict):
        def __init__(self, schema: Any = None) -> None:
            super().__init__(schema or {})

        def __call__(self, val: Any) -> Any:
            return val

    class Marker:
        def __init__(
            self, schema: Any, default: Any = None, description: Any = None
        ) -> None:
            self.schema = schema
            self.default = default
            self.description = description

    class Required(Marker):
        pass

    class Optional(Marker):
        pass

    vol.Schema = Schema
    vol.Required = Required
    vol.Optional = Optional
    sys.modules["voluptuous"] = vol

# Setup lightweight homeassistant mock if not installed in current environment
if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    data_entry_flow = types.ModuleType("homeassistant.data_entry_flow")
    const = types.ModuleType("homeassistant.const")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    storage = types.ModuleType("homeassistant.helpers.storage")
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    selector = types.ModuleType("homeassistant.helpers.selector")
    components = types.ModuleType("homeassistant.components")
    sensor = types.ModuleType("homeassistant.components.sensor")
    device_tracker = types.ModuleType("homeassistant.components.device_tracker")
    util = types.ModuleType("homeassistant.util")
    dt = types.ModuleType("homeassistant.util.dt")

    entity_platform.AddEntitiesCallback = Any

    # FlowResultType
    class FlowResultType(StrEnum):
        FORM = "form"
        CREATE_ENTRY = "create_entry"
        ABORT = "abort"

    data_entry_flow.FlowResultType = FlowResultType

    # Platform & Consts
    class Platform(StrEnum):
        SENSOR = "sensor"
        DEVICE_TRACKER = "device_tracker"

    class EntityCategory(StrEnum):
        DIAGNOSTIC = "diagnostic"
        CONFIG = "config"

    const.Platform = Platform
    const.EntityCategory = EntityCategory

    # ConfigFlow & OptionsFlow
    class ConfigFlow:
        def __init_subclass__(cls, **kwargs: Any) -> None:
            pass

        async def async_set_unique_id(self, unique_id: str) -> None:
            self._unique_id = unique_id

        def _abort_if_unique_id_configured(self) -> None:
            pass

        def _get_reconfigure_entry(self) -> Any:
            return getattr(self, "_reconfigure_entry", None)

        def async_show_form(
            self, *, step_id: str, data_schema: Any = None, errors: Any = None
        ) -> dict[str, Any]:
            return {
                "type": FlowResultType.FORM,
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
            }

        def async_create_entry(
            self, *, title: str, data: dict[str, Any]
        ) -> dict[str, Any]:
            return {"type": FlowResultType.CREATE_ENTRY, "title": title, "data": data}

        def async_update_reload_and_abort(
            self, entry: Any, *, data: dict[str, Any]
        ) -> dict[str, Any]:
            return {
                "type": FlowResultType.ABORT,
                "reason": "reconfigure_successful",
                "data": data,
            }

    class OptionsFlow:
        def async_show_form(
            self, *, step_id: str, data_schema: Any = None, errors: Any = None
        ) -> dict[str, Any]:
            return {
                "type": FlowResultType.FORM,
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
            }

        def async_create_entry(
            self, *, title: str, data: dict[str, Any]
        ) -> dict[str, Any]:
            return {"type": FlowResultType.CREATE_ENTRY, "title": title, "data": data}

    class ConfigEntry:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.entry_id = "test_entry"
            self.data: dict[str, Any] = {}
            self.options: dict[str, Any] = {}
            self.runtime_data: Any = None

    config_entries.ConfigFlow = ConfigFlow
    config_entries.OptionsFlow = OptionsFlow
    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigFlowResult = dict[str, Any]
    config_entries.SOURCE_USER = "user"

    # Core
    core.HomeAssistant = object
    core.callback = lambda fn: fn

    # Update coordinator
    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator:
        def __class_getitem__(cls, item: Any) -> type:
            return cls

        def __init__(
            self,
            hass: Any,
            logger: Any,
            *,
            name: str,
            update_interval: timedelta | None = None,
        ) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data: Any = None
            self.last_update_success = True

        async def async_config_entry_first_refresh(self) -> None:
            pass

    class CoordinatorEntity:
        def __class_getitem__(cls, item: Any) -> type:
            return cls

        def __init__(self, coordinator: Any) -> None:
            self.coordinator = coordinator
            self._attr_has_entity_name = True

        @property
        def available(self) -> bool:
            return getattr(self.coordinator, "last_update_success", True)

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.CoordinatorEntity = CoordinatorEntity
    update_coordinator.UpdateFailed = UpdateFailed

    # Storage Store
    class Store:
        def __class_getitem__(cls, item: Any) -> type:
            return cls

        def __init__(self, hass: Any, version: int, key: str) -> None:
            self.hass = hass
            self.version = version
            self.key = key

        async def async_load(self) -> Any:
            return None

        async def async_save(self, data: Any) -> None:
            pass

    storage.Store = Store

    # Device registry
    class DeviceEntryType(StrEnum):
        SERVICE = "service"

    class DeviceInfo(dict):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(kwargs)

    device_registry.DeviceEntryType = DeviceEntryType
    device_registry.DeviceInfo = DeviceInfo

    # Selectors
    class BaseSelector:
        def __init__(self, config: Any = None) -> None:
            self.config = config

    class SelectSelector(BaseSelector):
        pass

    class SelectSelectorConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    class SelectSelectorMode(StrEnum):
        LIST = "list"
        DROPDOWN = "dropdown"

    class SelectOptionDict(dict):
        pass

    class TextSelector(BaseSelector):
        pass

    class TextSelectorConfig:
        pass

    class NumberSelector(BaseSelector):
        pass

    class NumberSelectorConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    class NumberSelectorMode(StrEnum):
        BOX = "box"

    class BooleanSelector(BaseSelector):
        pass

    selector.SelectSelector = SelectSelector
    selector.SelectSelectorConfig = SelectSelectorConfig
    selector.SelectSelectorMode = SelectSelectorMode
    selector.SelectOptionDict = SelectOptionDict
    selector.TextSelector = TextSelector
    selector.TextSelectorConfig = TextSelectorConfig
    selector.NumberSelector = NumberSelector
    selector.NumberSelectorConfig = NumberSelectorConfig
    selector.NumberSelectorMode = NumberSelectorMode
    selector.BooleanSelector = BooleanSelector

    # Sensors
    class SensorDeviceClass(StrEnum):
        TIMESTAMP = "timestamp"
        DURATION = "duration"
        ENUM = "enum"
        MONETARY = "monetary"
        DISTANCE = "distance"

    class SensorStateClass(StrEnum):
        MEASUREMENT = "measurement"
        TOTAL = "total"

    class SensorEntity:
        pass

    from dataclasses import dataclass

    @dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription:
        key: str = ""
        device_class: Any = None
        state_class: Any = None
        native_unit_of_measurement: Any = None
        options: Any = None
        translation_key: Any = None
        entity_category: Any = None
        icon: Any = None
        has_entity_name: bool = False

    sensor.SensorDeviceClass = SensorDeviceClass
    sensor.SensorStateClass = SensorStateClass
    sensor.SensorEntity = SensorEntity
    sensor.SensorEntityDescription = SensorEntityDescription

    # Device Tracker
    class SourceType(StrEnum):
        GPS = "gps"

    class TrackerEntity:
        pass

    device_tracker.SourceType = SourceType
    device_tracker.TrackerEntity = TrackerEntity

    dt_const = types.ModuleType("homeassistant.components.device_tracker.const")
    dt_entity = types.ModuleType("homeassistant.components.device_tracker.entity")
    dt_const.SourceType = SourceType
    dt_entity.TrackerEntity = TrackerEntity
    device_tracker.const = dt_const
    device_tracker.entity = dt_entity
    sys.modules["homeassistant.components.device_tracker.const"] = dt_const
    sys.modules["homeassistant.components.device_tracker.entity"] = dt_entity

    # Aiohttp client
    aiohttp_client.async_get_clientsession = lambda hass: None

    # DT
    dt.now = lambda: datetime.now(UTC)
    dt.utcnow = lambda: datetime.now(UTC)

    # Register modules
    helpers.aiohttp_client = aiohttp_client
    helpers.storage = storage
    helpers.update_coordinator = update_coordinator
    helpers.device_registry = device_registry
    helpers.entity_platform = entity_platform
    helpers.selector = selector
    components.sensor = sensor
    components.device_tracker = device_tracker
    util.dt = dt

    ha.config_entries = config_entries
    ha.data_entry_flow = data_entry_flow
    ha.const = const
    ha.core = core
    ha.helpers = helpers
    ha.components = components
    ha.util = util

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.data_entry_flow"] = data_entry_flow
    sys.modules["homeassistant.const"] = const
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client
    sys.modules["homeassistant.helpers.storage"] = storage
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator
    sys.modules["homeassistant.helpers.device_registry"] = device_registry
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform
    sys.modules["homeassistant.helpers.selector"] = selector
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.sensor"] = sensor
    sys.modules["homeassistant.components.device_tracker"] = device_tracker
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.dt"] = dt


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> Any:
    """Enable custom integrations in tests."""
    yield


@pytest.fixture(autouse=True)
def fail_on_ha_deprecation_reports() -> Generator[None]:
    """Fail when Home Assistant logs deprecated use by this integration.

    Reports logged while modules were imported surface on the first test.
    """
    yield
    if reports := DEPRECATION_REPORTS.pop_reports():
        pytest.fail(
            "Home Assistant reported deprecated use by translink:\n"
            + "\n".join(reports),
            pytrace=False,
        )


@pytest.fixture
def plan_response_data() -> dict[str, Any]:
    """Load sample /api/plan response JSON."""
    with open(FIXTURES_DIR / "plan_response.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def sample_vehicle_positions_bytes() -> bytes:
    """Load sample GTFS-RT VehiclePositions protobuf payload."""
    with open(FIXTURES_DIR / "sample_vehicle_positions.pb", "rb") as f:
        return f.read()


@pytest.fixture
def sample_trip_updates_bytes() -> bytes:
    """Load sample GTFS-RT TripUpdates protobuf payload."""
    with open(FIXTURES_DIR / "sample_trip_updates.pb", "rb") as f:
        return f.read()
