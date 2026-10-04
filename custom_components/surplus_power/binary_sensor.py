"""Binary sensors for Surplus Power."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import SurplusPowerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up calibration-due sensor."""
    async_add_entities([CalibrationDueSensor(hass, entry)])


class CalibrationDueSensor(SurplusPowerEntity, BinarySensorEntity):
    """Report whether a full calibration is required."""

    _attr_translation_key = "calibration_due"
    _attr_icon = "mdi:battery-sync"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, "calibration_due")

    @property
    def is_on(self) -> bool:
        """Return true when calibration is required."""
        return self.runtime.controller.calibration_due
