"""Buttons for Surplus Power."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import SurplusPowerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the force-calibration button."""
    async_add_entities([ForceCalibrationButton(hass, entry)])


class ForceCalibrationButton(SurplusPowerEntity, ButtonEntity):
    """Request a forced full-charge calibration."""

    _attr_translation_key = "force_calibration"
    _attr_icon = "mdi:battery-sync"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, "force_calibration")

    async def async_press(self) -> None:
        """Request calibration."""
        await self.runtime.async_force_calibration()
