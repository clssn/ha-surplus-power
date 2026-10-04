"""Shared test data."""

from custom_components.surplus_power.const import (
    CONF_CHARGER_ENERGY_ENTITY,
    CONF_CHARGER_POWER_ENTITY,
    CONF_CHARGER_SWITCH_ENTITY,
    CONF_LOAD_ENERGY_ENTITY,
    CONF_LOAD_POWER_ENTITY,
    CONF_SURPLUS_POWER_ENTITY,
)

USER_INPUT = {
    CONF_SURPLUS_POWER_ENTITY: "sensor.site_surplus_power",
    CONF_CHARGER_SWITCH_ENTITY: "switch.battery_charger_input",
    CONF_CHARGER_POWER_ENTITY: "sensor.battery_charger_power",
    CONF_CHARGER_ENERGY_ENTITY: "sensor.battery_charger_energy",
    CONF_LOAD_POWER_ENTITY: "sensor.protected_load_power",
    CONF_LOAD_ENERGY_ENTITY: "sensor.protected_load_energy",
}
