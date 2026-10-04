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
    CONF_SURPLUS_POWER_ENTITY: "sensor.sensor_balanced_power_production",
    CONF_CHARGER_SWITCH_ENTITY: "switch.technikraum_batterie_eingang",
    CONF_CHARGER_POWER_ENTITY: "sensor.technikraum_batterie_eingang_leistung",
    CONF_CHARGER_ENERGY_ENTITY: "sensor.technikraum_batterie_eingang_energie",
    CONF_LOAD_POWER_ENTITY: "sensor.technikraum_ventilation_power_supply_leistung",
    CONF_LOAD_ENERGY_ENTITY: "sensor.technikraum_ventilation_power_supply_energie",
}
