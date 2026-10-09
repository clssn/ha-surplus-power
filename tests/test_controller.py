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
        last_charging_power_w=300,
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
        "load_power_w": 20,
        "load_energy_kwh": 4,
    }
    values.update(overrides)
    return Inputs(**values)  # type: ignore[arg-type]


def start_charging(controller: SurplusPowerController) -> None:
    controller.update(snapshot())
    probing = controller.update(snapshot(60))
    assert probing.command is ChargerCommand.TURN_ON
    assert probing.state is ControllerState.PROBING
    controller.update(snapshot(61, charger_is_on=True))
    result = controller.update(snapshot(120, charger_is_on=True))
    assert result.state is ControllerState.CHARGING


def test_sustained_surplus_starts_probe_then_charging() -> None:
    controller = configured_controller()
    assert controller.update(snapshot()).command is None
    probing = controller.update(snapshot(60))
    assert probing.command is ChargerCommand.TURN_ON
    assert probing.state is ControllerState.PROBING
    controller.update(snapshot(61, charger_is_on=True))
    result = controller.update(snapshot(120, charger_is_on=True))
    assert result.command is None
    assert result.state is ControllerState.CHARGING


def test_transient_surplus_does_not_start_charging() -> None:
    controller = configured_controller()
    controller.update(snapshot())
    controller.update(snapshot(30, surplus_power_w=49))
    result = controller.update(snapshot(60))
    assert result.command is None
    assert result.state is ControllerState.IDLE


def test_sustained_import_stops_charging() -> None:
    controller = configured_controller()
    start_charging(controller)
    controller.update(snapshot(121, charger_is_on=True, surplus_power_w=-1))
    result = controller.update(snapshot(181, charger_is_on=True, surplus_power_w=-1))
    assert result.command is ChargerCommand.TURN_OFF
    assert result.state is ControllerState.IDLE


def test_transient_import_does_not_stop_charging() -> None:
    controller = configured_controller()
    start_charging(controller)
    controller.update(snapshot(121, charger_is_on=True, surplus_power_w=-1))
    result = controller.update(snapshot(160, charger_is_on=True, surplus_power_w=0))
    assert result.command is None
    assert result.state is ControllerState.CHARGING


def test_manual_switch_off_returns_charging_to_idle() -> None:
    controller = configured_controller()
    start_charging(controller)
    controller.update(snapshot(121, charger_is_on=True))

    result = controller.update(snapshot(122, charger_is_on=False, charger_power_w=0))

    assert result.command is None
    assert result.state is ControllerState.IDLE


def test_idle_turns_off_unexpectedly_on_charger() -> None:
    controller = configured_controller()

    result = controller.update(snapshot(charger_is_on=True))

    assert result.command is ChargerCommand.TURN_OFF
    assert result.state is ControllerState.IDLE


def test_switch_feedback_delay_is_allowed_after_start_command() -> None:
    controller = configured_controller(switch_transition_timeout=timedelta(seconds=10))
    controller.update(snapshot())
    controller.update(snapshot(60))

    waiting = controller.update(snapshot(69, charger_is_on=False, charger_power_w=0))
    assert waiting.command is None
    assert waiting.state is ControllerState.PROBING
    assert controller.next_deadline == NOW + timedelta(seconds=70)

    timed_out = controller.update(snapshot(70, charger_is_on=False, charger_power_w=0))
    assert timed_out.command is None
    assert timed_out.state is ControllerState.IDLE


def test_bulk_power_is_observed_during_probe_but_taper_is_ignored() -> None:
    controller = configured_controller(minimum_observed_charging_power_w=50)
    controller.update(snapshot())
    controller.update(snapshot(60))
    controller.update(snapshot(61, charger_is_on=True, charger_power_w=400))
    assert controller.persisted.last_charging_power_w == 400
    controller.update(snapshot(62, charger_is_on=True, charger_power_w=200))
    controller.update(snapshot(63, charger_is_on=True, charger_power_w=5))
    assert controller.persisted.last_charging_power_w == 400


def test_new_probe_replaces_previous_session_power_with_current_peak() -> None:
    controller = configured_controller(minimum_observed_charging_power_w=50)
    controller.update(snapshot())
    controller.update(snapshot(60))
    controller.update(snapshot(61, charger_is_on=True, charger_power_w=240))

    assert controller.persisted.last_charging_power_w == 240


def test_probe_aborts_import_quickly_and_observes_cooldown() -> None:
    controller = configured_controller(
        probe_stop_duration=timedelta(seconds=5),
        probe_cooldown=timedelta(seconds=300),
    )
    controller.update(snapshot())
    controller.update(snapshot(60))
    controller.update(snapshot(61, charger_is_on=True, surplus_power_w=-1))
    result = controller.update(snapshot(66, charger_is_on=True, surplus_power_w=-1))
    assert result.command is ChargerCommand.TURN_OFF
    assert result.state is ControllerState.IDLE

    still_cooling_down = controller.update(snapshot(300, surplus_power_w=1000))
    assert still_cooling_down.command is None
    assert controller.next_deadline == NOW + timedelta(seconds=366)


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
    first = controller.update(snapshot(charger_power_w=5, surplus_power_w=-100))
    assert first.command is ChargerCommand.TURN_ON
    assert first.state is ControllerState.CALIBRATING
    controller.update(snapshot(1, charger_is_on=True, charger_power_w=5, surplus_power_w=-100))
    result = controller.update(
        snapshot(31, charger_is_on=True, charger_power_w=5, surplus_power_w=-100)
    )
    assert result.command is ChargerCommand.TURN_OFF
    assert result.state is ControllerState.IDLE
    assert controller.estimated_soc == 100
    assert controller.persisted.last_calibration == NOW + timedelta(seconds=31)


def test_full_battery_keeps_input_on_while_exporting() -> None:
    controller = SurplusPowerController(ControllerConfig())
    controller.update(snapshot(charger_power_w=5))
    controller.update(snapshot(1, charger_is_on=True, charger_power_w=5))

    full = controller.update(snapshot(31, charger_is_on=True, charger_power_w=5))
    assert full.command is None
    assert full.state is ControllerState.FULL
    assert controller.estimated_soc == 100

    still_full = controller.update(
        snapshot(120, charger_is_on=True, charger_power_w=5, surplus_power_w=100)
    )
    assert still_full.command is None
    assert still_full.state is ControllerState.FULL


def test_sustained_import_turns_off_full_battery_input() -> None:
    controller = SurplusPowerController(ControllerConfig())
    controller.update(snapshot(charger_power_w=5))
    controller.update(snapshot(1, charger_is_on=True, charger_power_w=5))
    controller.update(snapshot(31, charger_is_on=True, charger_power_w=5))

    controller.update(snapshot(32, charger_is_on=True, charger_power_w=5, surplus_power_w=-1))
    stopped = controller.update(
        snapshot(92, charger_is_on=True, charger_power_w=5, surplus_power_w=-1)
    )
    assert stopped.command is ChargerCommand.TURN_OFF
    assert stopped.state is ControllerState.IDLE


def test_transient_import_keeps_full_battery_input_on() -> None:
    controller = SurplusPowerController(ControllerConfig())
    controller.update(snapshot(charger_power_w=5))
    controller.update(snapshot(1, charger_is_on=True, charger_power_w=5))
    controller.update(snapshot(31, charger_is_on=True, charger_power_w=5))

    controller.update(snapshot(32, charger_is_on=True, charger_power_w=5, surplus_power_w=-1))
    recovered = controller.update(
        snapshot(60, charger_is_on=True, charger_power_w=5, surplus_power_w=1)
    )
    assert recovered.command is None
    assert recovered.state is ControllerState.FULL


def test_full_battery_returns_to_charging_when_power_rises() -> None:
    controller = SurplusPowerController(ControllerConfig())
    controller.update(snapshot(charger_power_w=5))
    controller.update(snapshot(1, charger_is_on=True, charger_power_w=5))
    controller.update(snapshot(31, charger_is_on=True, charger_power_w=5))

    charging = controller.update(
        snapshot(32, charger_is_on=True, charger_power_w=100, surplus_power_w=100)
    )
    assert charging.command is None
    assert charging.state is ControllerState.CHARGING


def test_full_detection_waits_for_switch_feedback() -> None:
    controller = SurplusPowerController(ControllerConfig())
    controller.update(snapshot(charger_power_w=0))
    controller.update(snapshot(60, charger_power_w=0))

    assert controller.state is ControllerState.CALIBRATING
    assert controller.estimated_soc == 0


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
    controller = configured_controller(
        disconnect_duration=timedelta(seconds=30),
        reconnect_duration=timedelta(seconds=30),
    )
    disconnected = controller.update(snapshot(charger_available=False))
    assert disconnected.state is ControllerState.IDLE
    assert disconnected.command is None

    assert controller.update(snapshot(30, charger_available=False)).state is (
        ControllerState.DISCONNECTED
    )
    assert controller.update(snapshot(31)).state is ControllerState.DISCONNECTED
    result = controller.update(snapshot(61))
    assert result.state is ControllerState.CALIBRATING
    assert result.command is ChargerCommand.TURN_ON


def test_brief_unavailability_does_not_require_recalibration() -> None:
    controller = configured_controller(disconnect_duration=timedelta(seconds=60))

    unavailable = controller.update(snapshot(charger_available=False))
    assert unavailable.state is ControllerState.IDLE
    assert unavailable.command is None
    assert controller.calibration_due is False
    assert controller.next_deadline == NOW + timedelta(seconds=60)

    recovered = controller.update(snapshot(30))
    assert recovered.state is ControllerState.IDLE
    assert recovered.command is None
    assert controller.calibration_due is False


def test_brief_unavailability_during_charging_resumes_charging() -> None:
    controller = configured_controller(disconnect_duration=timedelta(seconds=60))
    start_charging(controller)

    unavailable = controller.update(snapshot(121, charger_available=False))
    assert unavailable.state is ControllerState.CHARGING
    assert unavailable.command is None

    recovered = controller.update(snapshot(150, charger_is_on=True))
    assert recovered.state is ControllerState.CHARGING
    assert recovered.command is None
    assert controller.calibration_due is False


@pytest.mark.parametrize("missing", ["surplus_power_w", "charger_power_w"])
def test_missing_required_feedback_stops_normal_charging(missing: str) -> None:
    controller = configured_controller()
    start_charging(controller)
    result = controller.update(snapshot(121, charger_is_on=True, **{missing: None}))
    assert result.state is ControllerState.IDLE
    assert result.command is ChargerCommand.TURN_OFF


def test_controller_can_only_command_charger_input() -> None:
    assert set(ChargerCommand) == {ChargerCommand.TURN_ON, ChargerCommand.TURN_OFF}


def test_persisted_state_restores_without_forcing_calibration() -> None:
    persisted = PersistentState(
        estimated_energy_wh=800,
        last_charging_power_w=350,
        last_calibration=NOW,
        requires_recalibration=False,
    )
    restored = SurplusPowerController(ControllerConfig(), persisted)
    assert restored.state is ControllerState.IDLE
    assert restored.estimated_soc == pytest.approx(800 / 1056 * 100)


def test_sustained_load_meter_outage_starts_empty_battery_recovery() -> None:
    controller = configured_controller(load_outage_duration=timedelta(seconds=60))

    controller.update(snapshot(load_power_w=None, load_energy_kwh=None))
    brief = controller.update(snapshot(59, load_power_w=None, load_energy_kwh=None))
    assert brief.state is ControllerState.IDLE
    assert controller.persisted.estimated_energy_wh == 500

    recovery = controller.update(snapshot(60, load_power_w=None, load_energy_kwh=None))
    assert recovery.state is ControllerState.RECOVERING
    assert recovery.command is ChargerCommand.TURN_ON
    assert controller.persisted.estimated_energy_wh == 0
    assert controller.persisted.recovery_required is True
    assert controller.next_deadline == NOW + timedelta(days=7)


def test_low_estimated_reserve_forces_grid_charging_with_hysteresis() -> None:
    controller = configured_controller(
        capacity_wh=1000,
        charging_efficiency=0.8,
        reserve_start_fraction=0.2,
        recovery_target_fraction=0.3,
        load_recovery_duration=timedelta(seconds=30),
    )
    controller.persisted.estimated_energy_wh = 200

    started = controller.update(
        snapshot(charger_energy_kwh=10, load_energy_kwh=4, surplus_power_w=-500)
    )
    assert started.state is ControllerState.RECOVERING
    assert started.command is ChargerCommand.TURN_ON

    controller.update(
        snapshot(
            1,
            charger_is_on=True,
            charger_energy_kwh=10,
            load_energy_kwh=4,
            surplus_power_w=-500,
        )
    )
    below_target = controller.update(
        snapshot(
            30,
            charger_is_on=True,
            charger_energy_kwh=10.1,
            load_energy_kwh=4,
            surplus_power_w=-500,
        )
    )
    assert controller.persisted.estimated_energy_wh == pytest.approx(280)
    assert below_target.state is ControllerState.RECOVERING
    assert below_target.command is None

    recovered = controller.update(
        snapshot(
            31,
            charger_is_on=True,
            charger_energy_kwh=10.125,
            load_energy_kwh=4,
            surplus_power_w=-500,
        )
    )
    assert controller.persisted.estimated_energy_wh == pytest.approx(300)
    assert recovered.state is ControllerState.IDLE
    assert recovered.command is ChargerCommand.TURN_OFF


def test_estimate_above_reserve_start_does_not_force_grid_charging() -> None:
    controller = configured_controller(
        capacity_wh=1000,
        reserve_start_fraction=0.2,
        recovery_target_fraction=0.3,
    )
    controller.persisted.estimated_energy_wh = 201

    result = controller.update(snapshot(surplus_power_w=-500))

    assert result.state is ControllerState.IDLE
    assert result.command is None


@pytest.mark.parametrize("missing", ["load_power_w", "load_energy_kwh"])
def test_one_missing_load_measurement_does_not_imply_empty_battery(missing: str) -> None:
    controller = configured_controller(load_outage_duration=timedelta(seconds=60))

    controller.update(snapshot(surplus_power_w=0, **{missing: None}))
    result = controller.update(snapshot(60, surplus_power_w=0, **{missing: None}))

    assert result.state is ControllerState.IDLE
    assert controller.persisted.estimated_energy_wh == 500
    assert controller.persisted.recovery_required is False


def test_recovery_charges_to_reserve_then_stops_during_import() -> None:
    controller = configured_controller(
        capacity_wh=1000,
        charging_efficiency=0.8,
        load_outage_duration=timedelta(seconds=60),
        load_recovery_duration=timedelta(seconds=30),
        reserve_start_fraction=0.1,
        recovery_target_fraction=0.2,
    )
    controller.update(
        snapshot(
            charger_energy_kwh=10,
            load_power_w=None,
            load_energy_kwh=None,
            surplus_power_w=-100,
        )
    )
    controller.update(
        snapshot(
            60,
            charger_energy_kwh=10,
            load_power_w=None,
            load_energy_kwh=None,
            surplus_power_w=-100,
        )
    )
    controller.update(
        snapshot(
            61,
            charger_is_on=True,
            charger_energy_kwh=10,
            load_power_w=20,
            load_energy_kwh=4,
            surplus_power_w=-100,
        )
    )

    result = controller.update(
        snapshot(
            91,
            charger_is_on=True,
            charger_energy_kwh=10.25,
            load_power_w=20,
            load_energy_kwh=4,
            surplus_power_w=-100,
        )
    )

    assert controller.persisted.estimated_energy_wh == pytest.approx(200)
    assert controller.persisted.recovery_required is False
    assert result.state is ControllerState.IDLE
    assert result.command is ChargerCommand.TURN_OFF


def test_recovery_continues_as_normal_charging_when_exporting() -> None:
    controller = configured_controller(
        capacity_wh=1000,
        charging_efficiency=0.8,
        load_outage_duration=timedelta(seconds=1),
        load_recovery_duration=timedelta(seconds=1),
        reserve_start_fraction=0.1,
        recovery_target_fraction=0.2,
    )
    controller.update(snapshot(charger_energy_kwh=10, load_power_w=None, load_energy_kwh=None))
    controller.update(snapshot(1, charger_energy_kwh=10, load_power_w=None, load_energy_kwh=None))
    controller.update(
        snapshot(
            2,
            charger_is_on=True,
            charger_energy_kwh=10,
            load_power_w=20,
            load_energy_kwh=4,
        )
    )
    result = controller.update(
        snapshot(
            3,
            charger_is_on=True,
            charger_energy_kwh=10.25,
            load_power_w=20,
            load_energy_kwh=4,
        )
    )

    assert result.state is ControllerState.CHARGING
    assert result.command is None
    assert controller.persisted.recovery_required is False


def test_recovery_requirement_survives_restart() -> None:
    persisted = PersistentState(
        estimated_energy_wh=0,
        last_calibration=NOW,
        requires_recalibration=False,
        recovery_required=True,
    )

    restored = SurplusPowerController(ControllerConfig(), persisted)

    assert restored.state is ControllerState.RECOVERING
    assert restored.update(snapshot()).command is ChargerCommand.TURN_ON


def test_persistent_state_round_trip() -> None:
    original = PersistentState(
        estimated_energy_wh=321.5,
        last_charging_power_w=402.0,
        last_calibration=NOW,
        previous_charger_energy_kwh=12.3,
        previous_load_energy_kwh=4.5,
        requires_recalibration=False,
        recovery_required=True,
    )
    assert PersistentState.from_dict(original.as_dict()) == original


def test_next_deadline_tracks_active_hysteresis() -> None:
    controller = configured_controller()
    controller.update(snapshot())
    assert controller.next_deadline == NOW + timedelta(seconds=60)
    controller.update(snapshot(10, surplus_power_w=0))
    assert controller.next_deadline == NOW + timedelta(days=7)
