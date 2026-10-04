"""Focused tests for the Home Assistant command boundary."""

from types import SimpleNamespace

import pytest
from homeassistant.const import UnitOfEnergy
from homeassistant.core import State

from custom_components.surplus_power.const import CONF_CHARGER_SWITCH_ENTITY
from custom_components.surplus_power.controller import ChargerCommand
from custom_components.surplus_power.runtime import SurplusPowerRuntime, _energy_kwh


class RecordingServices:
    """Minimal service registry recording calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], bool]] = []

    async def async_call(
        self, domain: str, service: str, data: dict[str, str], *, blocking: bool
    ) -> None:
        self.calls.append((domain, service, data, blocking))


def runtime_for_actuator(entity_id: str) -> tuple[SurplusPowerRuntime, RecordingServices]:
    services = RecordingServices()
    runtime = object.__new__(SurplusPowerRuntime)
    runtime.settings = {CONF_CHARGER_SWITCH_ENTITY: entity_id}
    runtime.hass = SimpleNamespace(services=services)
    return runtime, services


async def test_actuator_boundary_rejects_non_switch_entity() -> None:
    runtime, services = runtime_for_actuator("switch.technikraum_batterie_eingang")
    await runtime._async_execute(ChargerCommand.TURN_OFF)
    assert services.calls == [
        (
            "switch",
            "turn_off",
            {"entity_id": "switch.technikraum_batterie_eingang"},
            True,
        )
    ]

    runtime.settings[CONF_CHARGER_SWITCH_ENTITY] = "sensor.ventilation_power"
    with pytest.raises(RuntimeError, match="non-switch"):
        await runtime._async_execute(ChargerCommand.TURN_OFF)
    assert len(services.calls) == 1


@pytest.mark.parametrize(
    ("unit", "value", "expected"),
    [
        (UnitOfEnergy.KILO_WATT_HOUR, "12.5", 12.5),
        (UnitOfEnergy.WATT_HOUR, "12500", 12.5),
        ("MJ", "45", None),
    ],
)
async def test_energy_unit_conversion(unit: str, value: str, expected: float | None) -> None:
    state = State("sensor.energy", value, {"unit_of_measurement": unit})
    assert _energy_kwh(state) == expected
