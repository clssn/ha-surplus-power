"""Tests for the HA-independent surplus charging controller."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.surplus_power.controller import (
    ChargerCommand,
    ControllerConfig,
    ControllerState,
    Inputs,
    PersistentState,
    SurplusPowerController,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def configured_controller(**config_overrides: object) -> SurplusPowerController:
    config = ControllerConfig(**config_overrides)
    persisted = PersistentState(
        estimated_energy_wh=500,
        expected_charging_power_w=300,
        last_calibration=NOW,
        requires_recalibration=False,
    )
    return SurplusPowerController(config, persisted)


def snapshot(seconds: int = 0, **overrides: object) -> Inputs:
    values: dict[str, object] = {
        "now": NOW + timedelta(seconds=seconds),
        "charger_available": True,
        "charger_is_on": False,
        "surplus_power_w": 400,
        "charger_power_w": 300,
    }
    values.update(overrides)
    return Inputs(**values)  # type: ignore[arg-type]


def start_charging(controller: SurplusPowerController) -> None:
    controller.update(snapshot())
    result = controller.update(snapshot(60))
    assert result.command is ChargerCommand.TURN_ON
    assert result.state is ControllerState.CHARGING


def test_sustained_surplus_starts_charging() -> None:
    controller = configured_controller()
    assert controller.update(snapshot()).command is None
    result = controller.update(snapshot(60))
    assert result.command is ChargerCommand.TURN_ON
    assert result.state is ControllerState.CHARGING


def test_transient_surplus_does_not_start_charging() -> None:
    controller = configured_controller()
    controller.update(snapshot())
    controller.update(snapshot(30, surplus_power_w=299))
    result = controller.update(snapshot(60))
    assert result.command is None
    assert result.state is ControllerState.IDLE


def test_sustained_import_stops_charging() -> None:
    controller = configured_controller()
    start_charging(controller)
    controller.update(snapshot(61, charger_is_on=True, surplus_power_w=-1))
    result = controller.update(snapshot(121, charger_is_on=True, surplus_power_w=-1))
    assert result.command is ChargerCommand.TURN_OFF
    assert result.state is ControllerState.IDLE


def test_transient_import_does_not_stop_charging() -> None:
    controller = configured_controller()
    start_charging(controller)
    controller.update(snapshot(61, charger_is_on=True, surplus_power_w=-1))
    result = controller.update(snapshot(100, charger_is_on=True, surplus_power_w=0))
    assert result.command is None
    assert result.state is ControllerState.CHARGING


def test_expected_power_is_learned_but_taper_is_ignored() -> None:
    controller = configured_controller(learning_alpha=0.5, learning_min_power_w=50)
    start_charging(controller)
    controller.update(snapshot(61, charger_is_on=True, charger_power_w=400))
    assert controller.persisted.expected_charging_power_w == pytest.approx(350)
    controller.update(snapshot(62, charger_is_on=True, charger_power_w=5))
    assert controller.persisted.expected_charging_power_w == pytest.approx(350)


def test_cumulative_energy_updates_battery_estimate() -> None:
    controller = configured_controller(charging_efficiency=0.8)
    controller.update(snapshot(charger_energy_kwh=10, load_energy_kwh=4))
    controller.update(snapshot(1, charger_energy_kwh=10.1, load_energy_kwh=4.02))
    assert controller.persisted.estimated_energy_wh == pytest.approx(560)


def test_negative_meter_delta_is_not_applied() -> None:
    controller = configured_controller()
    controller.update(snapshot(charger_energy_kwh=10, load_energy_kwh=4))
    controller.update(snapshot(1, charger_energy_kwh=1, load_energy_kwh=1))
    assert controller.persisted.estimated_energy_wh == 500
    controller.update(snapshot(2, charger_energy_kwh=1.1, load_energy_kwh=1.01))
    assert controller.persisted.estimated_energy_wh == pytest.approx(570)


def test_full_charge_calibration() -> None:
    controller = SurplusPowerController(ControllerConfig())
    first = controller.update(snapshot(charger_power_w=5))
    assert first.command is ChargerCommand.TURN_ON
    assert first.state is ControllerState.CALIBRATING
    controller.update(snapshot(1, charger_is_on=True, charger_power_w=5))
    result = controller.update(snapshot(31, charger_is_on=True, charger_power_w=5))
    assert result.command is ChargerCommand.TURN_OFF
    assert result.state is ControllerState.IDLE
    assert controller.estimated_soc == 100
    assert controller.persisted.last_calibration == NOW + timedelta(seconds=31)


def test_periodic_calibration_starts_and_ignores_surplus() -> None:
    controller = configured_controller(calibration_interval=timedelta(days=7))
    result = controller.update(
        Inputs(
            now=NOW + timedelta(days=7),
            charger_available=True,
            charger_is_on=False,
            surplus_power_w=-1000,
            charger_power_w=300,
        )
    )
    assert result.state is ControllerState.CALIBRATING
    assert result.command is ChargerCommand.TURN_ON


def test_disconnect_issues_no_command_and_reconnect_calibrates() -> None:
    controller = configured_controller(reconnect_duration=timedelta(seconds=30))
    disconnected = controller.update(snapshot(charger_available=False))
    assert disconnected.state is ControllerState.DISCONNECTED
    assert disconnected.command is None

    assert controller.update(snapshot(1)).state is ControllerState.DISCONNECTED
    result = controller.update(snapshot(31))
    assert result.state is ControllerState.CALIBRATING
    assert result.command is ChargerCommand.TURN_ON


@pytest.mark.parametrize("missing", ["surplus_power_w", "charger_power_w"])
def test_missing_required_feedback_stops_normal_charging(missing: str) -> None:
    controller = configured_controller()
    start_charging(controller)
    result = controller.update(snapshot(61, charger_is_on=True, **{missing: None}))
    assert result.state is ControllerState.IDLE
    assert result.command is ChargerCommand.TURN_OFF


def test_controller_can_only_command_charger_input() -> None:
    assert set(ChargerCommand) == {ChargerCommand.TURN_ON, ChargerCommand.TURN_OFF}


def test_persisted_state_restores_without_forcing_calibration() -> None:
    persisted = PersistentState(
        estimated_energy_wh=800,
        expected_charging_power_w=350,
        last_calibration=NOW,
        requires_recalibration=False,
    )
    restored = SurplusPowerController(ControllerConfig(), persisted)
    assert restored.state is ControllerState.IDLE
    assert restored.estimated_soc == pytest.approx(800 / 1056 * 100)


def test_persistent_state_round_trip() -> None:
    original = PersistentState(
        estimated_energy_wh=321.5,
        expected_charging_power_w=402.0,
        last_calibration=NOW,
        previous_charger_energy_kwh=12.3,
        previous_load_energy_kwh=4.5,
        requires_recalibration=False,
    )
    assert PersistentState.from_dict(original.as_dict()) == original


def test_next_deadline_tracks_active_hysteresis() -> None:
    controller = configured_controller()
    controller.update(snapshot())
    assert controller.next_deadline == NOW + timedelta(seconds=60)
    controller.update(snapshot(10, surplus_power_w=0))
    assert controller.next_deadline == NOW + timedelta(days=7)
