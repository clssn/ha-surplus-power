"""Config and options flows for Surplus Power."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CALIBRATION_INTERVAL_DAYS,
    CONF_CAPACITY_WH,
    CONF_CHARGER_ENERGY_ENTITY,
    CONF_CHARGER_POWER_ENTITY,
    CONF_CHARGER_SWITCH_ENTITY,
    CONF_CHARGING_EFFICIENCY,
    CONF_FULL_DETECTION_DURATION_S,
    CONF_FULL_POWER_THRESHOLD_W,
    CONF_INITIAL_CHARGING_POWER_W,
    CONF_LOAD_ENERGY_ENTITY,
    CONF_LOAD_POWER_ENTITY,
    CONF_RECONNECT_DURATION_S,
    CONF_START_DURATION_S,
    CONF_STOP_DURATION_S,
    CONF_SURPLUS_POWER_ENTITY,
    DEFAULTS,
    DOMAIN,
)

ENTITY_FIELDS = {
    CONF_SURPLUS_POWER_ENTITY: Platform.SENSOR,
    CONF_CHARGER_SWITCH_ENTITY: Platform.SWITCH,
    CONF_CHARGER_POWER_ENTITY: Platform.SENSOR,
    CONF_CHARGER_ENERGY_ENTITY: Platform.SENSOR,
    CONF_LOAD_POWER_ENTITY: Platform.SENSOR,
    CONF_LOAD_ENERGY_ENTITY: Platform.SENSOR,
}

OPTION_LIMITS = {
    CONF_CAPACITY_WH: (1, 100_000, 1),
    CONF_INITIAL_CHARGING_POWER_W: (1, 50_000, 1),
    CONF_CHARGING_EFFICIENCY: (0.01, 1.0, 0.01),
    CONF_START_DURATION_S: (0, 3600, 1),
    CONF_STOP_DURATION_S: (0, 3600, 1),
    CONF_FULL_POWER_THRESHOLD_W: (0, 1000, 1),
    CONF_FULL_DETECTION_DURATION_S: (1, 3600, 1),
    CONF_CALIBRATION_INTERVAL_DAYS: (0.01, 365, 0.01),
    CONF_RECONNECT_DURATION_S: (0, 3600, 1),
}


class SurplusPowerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure source entities."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Create a single controller entry."""
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_CHARGER_SWITCH_ENTITY])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Surplus Power", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_entity_schema())

    @staticmethod
    @callback
    def async_get_options_flow(
        _config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return tunable options flow."""
        return SurplusPowerOptionsFlow()


class SurplusPowerOptionsFlow(config_entries.OptionsFlow):
    """Configure controller tuning without HA helper entities."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit controller options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = DEFAULTS | dict(self.config_entry.options)
        return self.async_show_form(step_id="init", data_schema=_options_schema(current))


def _entity_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(key): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=platform)
            )
            for key, platform in ENTITY_FIELDS.items()
        }
    )


def _options_schema(current: dict[str, object]) -> vol.Schema:
    schema: dict[vol.Marker, object] = {}
    for key, (minimum, maximum, step) in OPTION_LIMITS.items():
        schema[vol.Required(key, default=current[key])] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=minimum,
                max=maximum,
                step=step,
                mode=selector.NumberSelectorMode.BOX,
            )
        )
    return vol.Schema(schema)
