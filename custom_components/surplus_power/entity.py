"""Shared diagnostic entity support."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN, SIGNAL_UPDATED
from .runtime import SurplusPowerRuntime


class SurplusPowerEntity(Entity):
    """Base class for entities backed by one controller runtime."""

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, key: str) -> None:
        self.runtime: SurplusPowerRuntime = hass.data[DOMAIN][entry.entry_id]
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title
        )
        self._signal = f"{SIGNAL_UPDATED}_{entry.entry_id}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to runtime updates."""
        self.async_on_remove(async_dispatcher_connect(self.hass, self._signal, self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
