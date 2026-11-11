"""Scheduled commute polling and persistence for Home Assistant."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, Literal

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api.models import PlanNotice
from .client import TranslinkApiError, TranslinkClient
from .const import (
    CONF_END_LOCATION_ID,
    CONF_END_NAME,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_START_LOCATION_ID,
    CONF_START_NAME,
    CONF_TRANSPORT_MODES,
    CONF_WINDOW_DELAY_STEP,
    CONF_WINDOW_DELAY_THRESHOLD,
    CONF_WINDOW_TRIP_LIMIT,
    DEFAULT_REALTIME_REGION,
    DEFAULT_TIME_SEARCH_MODE,
    DEFAULT_TRANSPORT_MODES,
    DEVICE_MODELS,
    DOMAIN,
    MODE_WINDOW,
    STORAGE_VERSION,
    WINDOW_OPTION_LIMITS,
    WINDOW_STORAGE_KEY_PREFIX,
)
from .window_alerts import (
    AlertLedgerEntry,
    RealtimeIndex,
    WindowAlert,
    WindowObservation,
    evaluate_window_trip,
    observe_window_trip,
)
from .window_matching import (
    WindowTrip,
    merge_window_trips,
    restore_trip,
    select_window_trips,
    trip_snapshot,
)
from .window_schedule import WindowOccurrence, WindowSchedule

_LOGGER = logging.getLogger(__name__)


def window_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    """Open the private per-entry ledger and grace snapshot."""
    return Store(
        hass,
        STORAGE_VERSION,
        f"{WINDOW_STORAGE_KEY_PREFIX}.{entry_id}",
        private=True,
        atomic_writes=True,
    )


@dataclass(frozen=True, slots=True)
class WindowData:
    """State and new automation events from one refresh."""

    status: Literal["idle", "active", "expired"]
    next_start: datetime | None
    occurrence: WindowOccurrence | None = None
    trips: tuple[WindowObservation, ...] = ()
    alerts: tuple[tuple[str, dict[str, Any]], ...] = ()

    def as_diagnostics(self) -> dict[str, Any]:
        """Expose current state without including the alert payload history."""
        occurrence = self.occurrence
        return {
            "status": self.status,
            "next_start": self.next_start.isoformat() if self.next_start else None,
            "occurrence": {
                "date": occurrence.date.isoformat(),
                "start": occurrence.start.isoformat(),
                "end": occurrence.end.isoformat(),
                "activation": occurrence.activation.isoformat(),
                "grace_end": occurrence.grace_end.isoformat(),
            }
            if occurrence
            else None,
            "trips": [trip.as_state() for trip in self.trips],
        }


class WindowCoordinator(DataUpdateCoordinator[WindowData]):
    """Track public-transit alternatives only while a commute window is active."""

    mode = MODE_WINDOW

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Set up a sleeping coordinator with per-entry persistent state."""
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"{DOMAIN}_{entry.entry_id}"
        )
        self.entry = entry
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_NAME, entry.title),
            manufacturer="Translink Queensland",
            model=DEVICE_MODELS[MODE_WINDOW],
            entry_type=DeviceEntryType.SERVICE,
        )
        self.client = TranslinkClient(session=async_get_clientsession(hass))
        config = {**entry.data, **entry.options}
        self.schedule = WindowSchedule.from_config(config)
        self._options = {
            key: max(minimum, min(maximum, int(config.get(key, default))))
            for key, (default, minimum, maximum) in WINDOW_OPTION_LIMITS.items()
        }
        self._scan = timedelta(seconds=self._options[CONF_SCAN_INTERVAL])
        self._limit = self._options[CONF_WINDOW_TRIP_LIMIT]
        self._store = window_store(hass, entry.entry_id)
        modes = entry.data.get(CONF_TRANSPORT_MODES) or DEFAULT_TRANSPORT_MODES
        self._scope = sha256(
            repr(
                (
                    entry.data[CONF_START_LOCATION_ID],
                    entry.data[CONF_END_LOCATION_ID],
                    self.schedule.identity,
                    tuple(sorted(set(modes))),
                )
            ).encode()
        ).hexdigest()
        self._stored: dict[str, Any] = {}
        self._ledger: dict[str, AlertLedgerEntry] = {}
        self._occurrence: WindowOccurrence | None = None
        self._tracked: tuple[WindowTrip, ...] = ()
        self._notices: dict[str, PlanNotice] = {}
        self._cancel_activation: CALLBACK_TYPE | None = None
        self._lock = asyncio.Lock()
        entry.async_on_unload(self._async_cancel_activation)

    @property
    def ledger_size(self) -> int:
        """Return a count without exposing the persisted records."""
        return len(self._ledger)

    async def _async_setup(self) -> None:
        """Load deduplication and public grace candidates for this occurrence."""
        self._stored = await self._store.async_load() or {}
        now = dt_util.utcnow()
        occurrence = self.schedule.occurrence_at(now)
        if (
            occurrence is None
            or now < occurrence.activation
            or self._stored.get("date") != occurrence.date.isoformat()
            or self._stored.get("scope") != self._scope
        ):
            return
        self._occurrence = occurrence
        self._ledger = {
            key: AlertLedgerEntry.from_storage(record)
            for key, record in self._stored["ledger"].items()
        }
        self._tracked = tuple(
            restore_trip(snapshot) for snapshot in self._stored["trips"][: self._limit]
        )
        self._notices = {
            key: PlanNotice.model_validate(notice)
            for key, notice in self._stored["notices"].items()
        }

    @callback
    def _async_cancel_activation(self) -> None:
        """Cancel the pending scheduled activation."""
        if self._cancel_activation is not None:
            self._cancel_activation()
            self._cancel_activation = None

    @callback
    def _async_activate(self, _now: datetime) -> None:
        """Refresh the entry at the start of its lead time."""
        self._cancel_activation = None
        if not self.entry.pref_disable_polling and not self.hass.is_stopping:
            self.entry.async_create_background_task(
                self.hass, self.async_refresh(), name=f"{self.name} window activation"
            )

    async def async_shutdown(self) -> None:
        """Cancel the activation and polling when the config entry unloads."""
        self._async_cancel_activation()
        await super().async_shutdown()

    def _next_occurrence(self, occurrence: WindowOccurrence) -> WindowOccurrence | None:
        if self.schedule.once is not None:
            return None
        return self.schedule.next_after(occurrence)

    async def _async_inactive(self, upcoming: WindowOccurrence | None) -> WindowData:
        self.update_interval = None
        self._async_cancel_activation()
        self._occurrence = None
        self._tracked = ()
        self._notices = {}
        self._ledger = {}
        await self._async_save_state({})
        if upcoming is None:
            return WindowData("expired", None)
        if not self.entry.pref_disable_polling:
            self._cancel_activation = async_track_point_in_utc_time(
                self.hass, self._async_activate, upcoming.activation
            )
        return WindowData("idle", upcoming.start)

    async def _async_save_state(self, state: dict[str, Any]) -> None:
        if state != self._stored:
            # Commit deduplication before handing events to the entity.
            await self._store.async_save(state)
            self._stored = state

    async def _async_update_data(self) -> WindowData:
        """Serialize refreshes so a manual update cannot emit an alert twice."""
        async with self._lock:
            return await self._async_poll()

    async def _async_poll(self) -> WindowData:
        now = dt_util.utcnow()
        occurrence = self.schedule.occurrence_at(now)
        if occurrence is None or now < occurrence.activation:
            return await self._async_inactive(occurrence)

        tracked = self._tracked if self._occurrence == occurrence else ()
        notices = self._notices if self._occurrence == occurrence else {}
        ledger = dict(self._ledger) if self._occurrence == occurrence else {}
        upcoming = self._next_occurrence(occurrence)
        after_end = now >= occurrence.end
        if after_end and not self._outstanding(tracked, now):
            return await self._async_inactive(upcoming)

        self._async_cancel_activation()
        self.update_interval = self._scan
        if not after_end:
            data = self.entry.data
            try:
                plan = await self.client.plan_journey(
                    start_location_id=data[CONF_START_LOCATION_ID],
                    start_name=data[CONF_START_NAME],
                    end_location_id=data[CONF_END_LOCATION_ID],
                    end_name=data[CONF_END_NAME],
                    transport_modes=data.get(
                        CONF_TRANSPORT_MODES, DEFAULT_TRANSPORT_MODES
                    ),
                    target_datetime=max(now, occurrence.start),
                    time_search_mode=DEFAULT_TIME_SEARCH_MODE,
                )
            except (TranslinkApiError, ValueError) as err:
                raise UpdateFailed(
                    f"Translink commute planning failed: {type(err).__name__}"
                ) from err
            selected = select_window_trips(plan.itineraries, occurrence, self._limit)
            tracked = merge_window_trips(tracked, selected, now, self._limit)
            notices = {
                str(notice.id): notice
                for notice in plan.notices
                if notice.id is not None
            }

        now = dt_util.utcnow()
        if now >= occurrence.grace_end:
            return await self._async_inactive(upcoming)
        if now >= occurrence.end:
            tracked = self._outstanding(tracked, now)
            if not tracked:
                return await self._async_inactive(upcoming)

        realtime = await self._async_realtime(tracked)
        now = dt_util.utcnow()
        if now >= occurrence.grace_end:
            return await self._async_inactive(upcoming)

        observations = tuple(
            observe_window_trip(trip, realtime, now, notices) for trip in tracked
        )
        events: list[tuple[str, dict[str, Any]]] = []
        for observation in observations:
            key = observation.trip.key
            record, changes = evaluate_window_trip(
                observation,
                ledger.get(key, AlertLedgerEntry()),
                threshold=self._options[CONF_WINDOW_DELAY_THRESHOLD],
                step=self._options[CONF_WINDOW_DELAY_STEP],
            )
            if changes:
                ledger[key] = record
                events.extend(
                    self._event_payload(occurrence, observation, change)
                    for change in changes
                )

        tracked = tuple(observation.trip for observation in observations)
        await self._async_persist(occurrence, tracked, notices, ledger)
        self._occurrence = occurrence
        self._tracked = tracked
        self._notices = notices
        self._ledger = ledger

        if now >= occurrence.end and not self._outstanding(tracked, now):
            return await self._async_inactive(upcoming)

        next_start = (
            occurrence.start
            if now < occurrence.start
            else upcoming.start
            if upcoming
            else None
        )
        return WindowData("active", next_start, occurrence, observations, tuple(events))

    @staticmethod
    def _outstanding(
        trips: tuple[WindowTrip, ...], now: datetime
    ) -> tuple[WindowTrip, ...]:
        return tuple(
            trip
            for trip in trips
            if not trip.departed and now <= trip.effective_departure
        )

    async def _async_realtime(self, trips: tuple[WindowTrip, ...]) -> RealtimeIndex:
        if any(trip.returned and not trip.departed for trip in trips):
            try:
                return RealtimeIndex(
                    await self.client.fetch_trip_updates(
                        DEFAULT_REALTIME_REGION, preserve_stale=True
                    )
                )
            except (TranslinkApiError, OSError, ValueError, IndexError) as err:
                _LOGGER.debug("Commute window realtime updates unavailable: %s", err)
        return RealtimeIndex({})

    async def _async_persist(
        self,
        occurrence: WindowOccurrence,
        tracked: tuple[WindowTrip, ...],
        notices: dict[str, PlanNotice],
        ledger: dict[str, AlertLedgerEntry],
    ) -> None:
        snapshots = [
            snapshot
            for trip in tracked
            if (snapshot := trip_snapshot(trip)) is not None
        ]
        notice_keys = {
            str(notice["id"])
            for snapshot in snapshots
            for leg in snapshot["legs"]
            for notice in leg["notices"]
        }
        await self._async_save_state(
            {
                "scope": self._scope,
                "date": occurrence.date.isoformat(),
                "ledger": {key: record.to_storage() for key, record in ledger.items()},
                "trips": snapshots,
                "notices": {
                    key: notice.model_dump(
                        include={"id", "title", "effect", "startsUtc", "endsUtc"}
                    )
                    for key, notice in notices.items()
                    if key in notice_keys
                },
            }
        )

    @staticmethod
    def _event_payload(
        occurrence: WindowOccurrence, observation: WindowObservation, alert: WindowAlert
    ) -> tuple[str, dict[str, Any]]:
        trip = observation.trip
        payload = {
            "occurrence_date": occurrence.date.isoformat(),
            "window_start": occurrence.start.isoformat(),
            "window_end": occurrence.end.isoformat(),
            "fingerprint": trip.key,
            "route": trip.route,
            "scheduled_departure": trip.departure.isoformat(),
            "delay_minutes": alert.delay,
            "previous_delay_minutes": alert.previous_delay,
            "realtime_updated_at": (
                observation.updated_at.isoformat() if observation.updated_at else None
            ),
        }
        if alert.notice is not None:
            payload.update(
                notice_id=alert.notice.id,
                notice_title=alert.notice.title,
                notice_effect=alert.notice.effect,
            )
        return alert.event_type, payload
