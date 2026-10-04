"""Surplus Power integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import (
    CONF_CHARGER_ENERGY_ENTITY,
    CONF_CHARGER_POWER_ENTITY,
    CONF_CHARGER_SWITCH_ENTITY,
    CONF_LOAD_ENERGY_ENTITY,
    DOMAIN,
    PLATFORMS,
)

CALIBRATION_ENTITY_KEYS = (
    CONF_CHARGER_SWITCH_ENTITY,
    CONF_CHARGER_POWER_ENTITY,
    CONF_CHARGER_ENERGY_ENTITY,
    CONF_LOAD_ENERGY_ENTITY,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .runtime import SurplusPowerRuntime


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Surplus Power from a config entry."""
    from .runtime import SurplusPowerRuntime

    runtime = await SurplusPowerRuntime.async_create(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    await runtime.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        runtime: SurplusPowerRuntime = hass.data[DOMAIN].pop(entry.entry_id)
        await runtime.async_stop()
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after options change."""
    runtime: SurplusPowerRuntime | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is not None:
        new_settings = dict(entry.data) | dict(entry.options)
        if any(
            runtime.settings.get(key) != new_settings.get(key) for key in CALIBRATION_ENTITY_KEYS
        ):
            runtime.controller.request_calibration()
        if runtime.settings.get(CONF_CHARGER_ENERGY_ENTITY) != new_settings.get(
            CONF_CHARGER_ENERGY_ENTITY
        ):
            runtime.controller.persisted.previous_charger_energy_kwh = None
        if runtime.settings.get(CONF_LOAD_ENERGY_ENTITY) != new_settings.get(
            CONF_LOAD_ENERGY_ENTITY
        ):
            runtime.controller.persisted.previous_load_energy_kwh = None
    await hass.config_entries.async_reload(entry.entry_id)
