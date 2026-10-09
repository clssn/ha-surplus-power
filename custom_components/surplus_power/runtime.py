"""Home Assistant adapter for the surplus charging controller."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfEnergy
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    CONF_CHARGER_ENERGY_ENTITY,
    CONF_CHARGER_POWER_ENTITY,
    CONF_CHARGER_SWITCH_ENTITY,
    CONF_LOAD_ENERGY_ENTITY,
    CONF_LOAD_POWER_ENTITY,
    CONF_SURPLUS_POWER_ENTITY,
    SIGNAL_UPDATED,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
    controller_config_from_mapping,
)
from .controller import (
    ChargerCommand,
    Inputs,
    PersistentState,
    SurplusPowerController,
)


class SurplusPowerRuntime:
    """Translate HA state events into deterministic controller updates."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, persisted: PersistentState) -> None:
        self.hass = hass
        self.entry = entry
        self.settings = dict(entry.data) | dict(entry.options)
        self.controller = SurplusPowerController(
            controller_config_from_mapping(self.settings), persisted
        )
        self.store: Store[dict[str, object]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry.entry_id}"
        )
        self._remove_listeners: list[Callable[[], None]] = []
        self._cancel_deadline: Callable[[], None] | None = None
        self._refresh_lock = asyncio.Lock()

    @classmethod
    async def async_create(cls, hass: HomeAssistant, entry: ConfigEntry) -> SurplusPowerRuntime:
        """Load persisted state and create the runtime."""
        store: Store[dict[str, object]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry.entry_id}"
        )
        stored = await store.async_load()
        persisted = PersistentState.from_dict(stored) if stored else PersistentState()
        runtime = cls(hass, entry, persisted)
        runtime.store = store
        return runtime

    async def async_start(self) -> None:
        """Subscribe to source states and evaluate the initial snapshot."""
        entities = {
            self.settings[CONF_SURPLUS_POWER_ENTITY],
            self.settings[CONF_CHARGER_SWITCH_ENTITY],
            self.settings[CONF_CHARGER_POWER_ENTITY],
            self.settings[CONF_CHARGER_ENERGY_ENTITY],
            self.settings[CONF_LOAD_ENERGY_ENTITY],
            self.settings[CONF_LOAD_POWER_ENTITY],
        }
        self._remove_listeners.append(
            async_track_state_change_event(self.hass, entities, self._state_changed)
        )
        await self.async_refresh()

    async def async_stop(self) -> None:
        """Remove listeners and persist final state."""
        for remove in self._remove_listeners:
            remove()
        self._remove_listeners.clear()
        if self._cancel_deadline is not None:
            self._cancel_deadline()
            self._cancel_deadline = None
        await self.store.async_save(self.controller.persisted.as_dict())

    @callback
    def _state_changed(self, _event: Event[dict[str, Any]]) -> None:
        self.hass.async_create_task(self.async_refresh())

    async def async_refresh(self) -> None:
        """Evaluate current HA states, execute a safe command, and reschedule."""
        async with self._refresh_lock:
            result = self.controller.update(self._snapshot())
            if result.command is not None:
                await self._async_execute(result.command)
            if result.persistent_state_changed:
                await self.store.async_save(self.controller.persisted.as_dict())
            self._schedule_deadline()
            async_dispatcher_send(self.hass, f"{SIGNAL_UPDATED}_{self.entry.entry_id}")

    async def async_force_calibration(self) -> None:
        """Request a full-charge calibration."""
        self.controller.request_calibration()
        await self.async_refresh()

    def _snapshot(self) -> Inputs:
        switch = self.hass.states.get(self.settings[CONF_CHARGER_SWITCH_ENTITY])
        charger_power = self.hass.states.get(self.settings[CONF_CHARGER_POWER_ENTITY])
        charger_energy = self.hass.states.get(self.settings[CONF_CHARGER_ENERGY_ENTITY])
        surplus = self.hass.states.get(self.settings[CONF_SURPLUS_POWER_ENTITY])
        load_energy = self.hass.states.get(self.settings[CONF_LOAD_ENERGY_ENTITY])
        load_power = self.hass.states.get(self.settings[CONF_LOAD_POWER_ENTITY])
        return Inputs(
            now=datetime.now(UTC),
            charger_available=_available(switch) and _available(charger_energy),
            charger_is_on=switch.state == STATE_ON if _available(switch) else None,
            surplus_power_w=_number(surplus),
            charger_power_w=_number(charger_power),
            charger_energy_kwh=_energy_kwh(charger_energy),
            load_power_w=_number(load_power),
            load_energy_kwh=_energy_kwh(load_energy),
        )

    async def _async_execute(self, command: ChargerCommand) -> None:
        entity_id = str(self.settings[CONF_CHARGER_SWITCH_ENTITY])
        if not entity_id.startswith("switch."):
            raise RuntimeError("Refusing to control a non-switch charger entity")
        service = "turn_on" if command is ChargerCommand.TURN_ON else "turn_off"
        await self.hass.services.async_call(
            "switch", service, {"entity_id": entity_id}, blocking=True
        )

    def _schedule_deadline(self) -> None:
        if self._cancel_deadline is not None:
            self._cancel_deadline()
            self._cancel_deadline = None
        deadline = self.controller.next_deadline
        if deadline is None:
            return
        delay = max(0.0, (deadline - datetime.now(UTC)).total_seconds())

        @callback
        def deadline_reached(_now: datetime) -> None:
            self._cancel_deadline = None
            self.hass.async_create_task(self.async_refresh())

        self._cancel_deadline = async_call_later(self.hass, delay, deadline_reached)


def _available(state: State | None) -> bool:
    return state is not None and state.state not in {STATE_UNKNOWN, STATE_UNAVAILABLE}


def _number(state: State | None) -> float | None:
    if not _available(state):
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


def _energy_kwh(state: State | None) -> float | None:
    value = _number(state)
    if value is None or state is None:
        return None
    unit = state.attributes.get("unit_of_measurement")
    if unit == UnitOfEnergy.WATT_HOUR:
        return value / 1000
    if unit == UnitOfEnergy.KILO_WATT_HOUR:
        return value
    return None
