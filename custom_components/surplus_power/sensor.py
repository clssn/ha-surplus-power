"""Diagnostic sensors for Surplus Power."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import SurplusPowerEntity
from .runtime import SurplusPowerRuntime


@dataclass(frozen=True, kw_only=True)
class SurplusSensorDescription(SensorEntityDescription):
    """Describe a controller diagnostic sensor."""

    value_fn: Callable[[SurplusPowerRuntime], str | float | datetime | None]


SENSORS = (
    SurplusSensorDescription(
        key="estimated_soc",
        translation_key="estimated_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        suggested_display_precision=1,
        value_fn=lambda runtime: runtime.controller.estimated_soc,
    ),
    SurplusSensorDescription(
        key="estimated_energy",
        translation_key="estimated_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        suggested_display_precision=1,
        value_fn=lambda runtime: runtime.controller.persisted.estimated_energy_wh,
    ),
    SurplusSensorDescription(
        key="controller_state",
        translation_key="controller_state",
        device_class=SensorDeviceClass.ENUM,
        options=[
            "disconnected",
            "needs_calibration",
            "calibrating",
            "idle",
            "probing",
            "charging",
            "full",
        ],
        value_fn=lambda runtime: runtime.controller.state.value,
    ),
    SurplusSensorDescription(
        # Preserve the original entity unique ID across the diagnostic rename.
        key="expected_charging_power",
        translation_key="observed_charging_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        suggested_display_precision=1,
        value_fn=lambda runtime: runtime.controller.persisted.last_charging_power_w,
    ),
    SurplusSensorDescription(
        key="last_calibration",
        translation_key="last_calibration",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda runtime: runtime.controller.persisted.last_calibration,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up controller sensors."""
    async_add_entities(SurplusPowerSensor(hass, entry, description) for description in SENSORS)


class SurplusPowerSensor(SurplusPowerEntity, SensorEntity):
    """A controller diagnostic sensor."""

    entity_description: SurplusSensorDescription

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        description: SurplusSensorDescription,
    ) -> None:
        super().__init__(hass, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | float | datetime | None:
        """Return current diagnostic value."""
        return self.entity_description.value_fn(self.runtime)
