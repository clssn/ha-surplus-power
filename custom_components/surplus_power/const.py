"""Constants for the Surplus Power integration."""

from datetime import timedelta
from typing import Final

DOMAIN = "surplus_power"
PLATFORMS = ("sensor", "binary_sensor", "button")

CONF_SURPLUS_POWER_ENTITY = "surplus_power_entity"
CONF_CHARGER_SWITCH_ENTITY = "charger_switch_entity"
CONF_CHARGER_POWER_ENTITY = "charger_power_entity"
CONF_CHARGER_ENERGY_ENTITY = "charger_energy_entity"
CONF_LOAD_POWER_ENTITY = "load_power_entity"
CONF_LOAD_ENERGY_ENTITY = "load_energy_entity"

CONF_CAPACITY_WH = "capacity_wh"
CONF_CHARGING_EFFICIENCY = "charging_efficiency"
CONF_INITIAL_CHARGING_POWER_W = "initial_charging_power_w"
CONF_START_DURATION_S = "start_duration_s"
CONF_STOP_DURATION_S = "stop_duration_s"
CONF_FULL_POWER_THRESHOLD_W = "full_power_threshold_w"
CONF_FULL_DETECTION_DURATION_S = "full_detection_duration_s"
CONF_CALIBRATION_INTERVAL_DAYS = "calibration_interval_days"
CONF_RECONNECT_DURATION_S = "reconnect_duration_s"

DEFAULTS: Final = {
    CONF_CAPACITY_WH: 1056.0,
    CONF_CHARGING_EFFICIENCY: 0.80,
    CONF_INITIAL_CHARGING_POWER_W: 300.0,
    CONF_START_DURATION_S: 60,
    CONF_STOP_DURATION_S: 60,
    CONF_FULL_POWER_THRESHOLD_W: 10.0,
    CONF_FULL_DETECTION_DURATION_S: 30,
    CONF_CALIBRATION_INTERVAL_DAYS: 7,
    CONF_RECONNECT_DURATION_S: 30,
}

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}.state"
SIGNAL_UPDATED = f"{DOMAIN}_updated"


def controller_config_from_mapping(data: dict[str, object]):
    """Build controller configuration from config-entry values."""
    from .controller import ControllerConfig

    values = DEFAULTS | data
    return ControllerConfig(
        capacity_wh=float(values[CONF_CAPACITY_WH]),
        charging_efficiency=float(values[CONF_CHARGING_EFFICIENCY]),
        initial_charging_power_w=float(values[CONF_INITIAL_CHARGING_POWER_W]),
        start_duration=timedelta(seconds=float(values[CONF_START_DURATION_S])),
        stop_duration=timedelta(seconds=float(values[CONF_STOP_DURATION_S])),
        full_power_threshold_w=float(values[CONF_FULL_POWER_THRESHOLD_W]),
        full_detection_duration=timedelta(seconds=float(values[CONF_FULL_DETECTION_DURATION_S])),
        calibration_interval=timedelta(days=float(values[CONF_CALIBRATION_INTERVAL_DAYS])),
        reconnect_duration=timedelta(seconds=float(values[CONF_RECONNECT_DURATION_S])),
    )
