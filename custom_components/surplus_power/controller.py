"""HA-independent surplus charging controller.

This module deliberately knows nothing about Home Assistant services or entity
IDs. It can request only charger input commands; the ventilation/load is always
a read-only measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite


class ControllerState(StrEnum):
    """Explicit controller states."""

    DISCONNECTED = "disconnected"
    NEEDS_CALIBRATION = "needs_calibration"
    CALIBRATING = "calibrating"
    IDLE = "idle"
    CHARGING = "charging"


class ChargerCommand(StrEnum):
    """The complete actuator vocabulary exposed by the controller."""

    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"


@dataclass(frozen=True, slots=True)
class ControllerConfig:
    """Controller tuning parameters."""

    capacity_wh: float = 1056.0
    charging_efficiency: float = 0.80
    initial_charging_power_w: float = 300.0
    start_duration: timedelta = timedelta(seconds=60)
    stop_duration: timedelta = timedelta(seconds=60)
    full_power_threshold_w: float = 10.0
    full_detection_duration: timedelta = timedelta(seconds=30)
    calibration_interval: timedelta = timedelta(days=7)
    reconnect_duration: timedelta = timedelta(seconds=30)
    learning_alpha: float = 0.2
    learning_min_power_w: float = 50.0

    def __post_init__(self) -> None:
        if self.capacity_wh <= 0:
            raise ValueError("capacity_wh must be positive")
        if not 0 < self.charging_efficiency <= 1:
            raise ValueError("charging_efficiency must be in (0, 1]")
        if self.initial_charging_power_w <= 0:
            raise ValueError("initial_charging_power_w must be positive")
        if not 0 < self.learning_alpha <= 1:
            raise ValueError("learning_alpha must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class Inputs:
    """A timestamped snapshot of controller inputs.

    Cumulative energy readings are expressed in kWh, matching common HA energy
    sensors. Missing numeric values are represented by ``None``.
    """

    now: datetime
    charger_available: bool
    charger_is_on: bool | None = None
    surplus_power_w: float | None = None
    charger_power_w: float | None = None
    charger_energy_kwh: float | None = None
    load_energy_kwh: float | None = None


@dataclass(slots=True)
class PersistentState:
    """State suitable for integration-local persistence."""

    estimated_energy_wh: float = 0.0
    expected_charging_power_w: float | None = None
    last_calibration: datetime | None = None
    previous_charger_energy_kwh: float | None = None
    previous_load_energy_kwh: float | None = None
    requires_recalibration: bool = True

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "estimated_energy_wh": self.estimated_energy_wh,
            "expected_charging_power_w": self.expected_charging_power_w,
            "last_calibration": (
                self.last_calibration.isoformat() if self.last_calibration is not None else None
            ),
            "previous_charger_energy_kwh": self.previous_charger_energy_kwh,
            "previous_load_energy_kwh": self.previous_load_energy_kwh,
            "requires_recalibration": self.requires_recalibration,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> PersistentState:
        """Restore persisted state, ignoring absent values conservatively."""
        raw_calibration = data.get("last_calibration")
        last_calibration = (
            datetime.fromisoformat(raw_calibration) if isinstance(raw_calibration, str) else None
        )
        return cls(
            estimated_energy_wh=float(data.get("estimated_energy_wh", 0.0)),
            expected_charging_power_w=_optional_float(data.get("expected_charging_power_w")),
            last_calibration=last_calibration,
            previous_charger_energy_kwh=_optional_float(data.get("previous_charger_energy_kwh")),
            previous_load_energy_kwh=_optional_float(data.get("previous_load_energy_kwh")),
            requires_recalibration=bool(data.get("requires_recalibration", True)),
        )


@dataclass(frozen=True, slots=True)
class ControllerResult:
    """Result of processing one snapshot."""

    state: ControllerState
    command: ChargerCommand | None
    persistent_state_changed: bool


class SurplusPowerController:
    """Deterministic state machine for charging and battery estimation."""

    def __init__(
        self,
        config: ControllerConfig,
        persisted: PersistentState | None = None,
    ) -> None:
        self.config = config
        self.persisted = persisted or PersistentState()
        if self.persisted.expected_charging_power_w is None:
            self.persisted.expected_charging_power_w = config.initial_charging_power_w
        self.state = (
            ControllerState.NEEDS_CALIBRATION
            if self.persisted.requires_recalibration
            else ControllerState.IDLE
        )
        self._condition_since: datetime | None = None
        self._available_since: datetime | None = None
        self._last_inputs: Inputs | None = None

    @property
    def estimated_soc(self) -> float:
        """Return estimated charge percentage, clamped to valid bounds."""
        return 100.0 * self.persisted.estimated_energy_wh / self.config.capacity_wh

    @property
    def calibration_due(self) -> bool:
        """Return whether calibration is required independent of wall clock."""
        return self.persisted.requires_recalibration

    @property
    def next_deadline(self) -> datetime | None:
        """Return the next instant at which time alone may cause a transition."""
        if self._condition_since is not None:
            durations = {
                ControllerState.IDLE: self.config.start_duration,
                ControllerState.CHARGING: self.config.stop_duration,
                ControllerState.CALIBRATING: self.config.full_detection_duration,
            }
            duration = durations.get(self.state)
            if duration is not None:
                return self._condition_since + duration
        if self.state is ControllerState.DISCONNECTED and self._available_since is not None:
            return self._available_since + self.config.reconnect_duration
        if self.persisted.last_calibration is not None and not self.calibration_due:
            return self.persisted.last_calibration + self.config.calibration_interval
        return None

    def request_calibration(self) -> None:
        """Request calibration at the next input evaluation."""
        self.persisted.requires_recalibration = True
        if self.state not in {ControllerState.DISCONNECTED, ControllerState.CALIBRATING}:
            self.state = ControllerState.NEEDS_CALIBRATION
            self._condition_since = None

    def update(self, inputs: Inputs) -> ControllerResult:
        """Process a complete input snapshot and optionally request one command."""
        if self._last_inputs is not None and inputs.now < self._last_inputs.now:
            raise ValueError("inputs.now must be monotonic")

        before = self._persistent_fingerprint()
        self._update_energy(inputs)
        self._mark_periodic_calibration(inputs.now)

        command: ChargerCommand | None = None
        if not inputs.charger_available:
            self.state = ControllerState.DISCONNECTED
            self.persisted.requires_recalibration = True
            self._available_since = None
            self._condition_since = None
        elif self.state is ControllerState.DISCONNECTED:
            if self._available_since is None:
                self._available_since = inputs.now
            elif inputs.now - self._available_since >= self.config.reconnect_duration:
                self.state = ControllerState.NEEDS_CALIBRATION
                self._condition_since = None
        elif self.persisted.requires_recalibration and self.state not in {
            ControllerState.CALIBRATING,
            ControllerState.NEEDS_CALIBRATION,
        }:
            self.state = ControllerState.NEEDS_CALIBRATION

        if self.state is ControllerState.NEEDS_CALIBRATION and inputs.charger_available:
            self.state = ControllerState.CALIBRATING
            self._condition_since = None
            if inputs.charger_is_on is not True:
                command = ChargerCommand.TURN_ON
        elif self.state is ControllerState.CALIBRATING:
            command = self._update_calibration(inputs)
        elif self.state is ControllerState.IDLE:
            command = self._update_idle(inputs)
        elif self.state is ControllerState.CHARGING:
            command = self._update_charging(inputs)

        self._last_inputs = inputs
        return ControllerResult(self.state, command, before != self._persistent_fingerprint())

    def _update_idle(self, inputs: Inputs) -> ChargerCommand | None:
        expected = self.persisted.expected_charging_power_w
        assert expected is not None
        if inputs.surplus_power_w is not None and inputs.surplus_power_w >= expected:
            if self._condition_since is None:
                self._condition_since = inputs.now
            elif inputs.now - self._condition_since >= self.config.start_duration:
                self.state = ControllerState.CHARGING
                self._condition_since = None
                return ChargerCommand.TURN_ON
        else:
            self._condition_since = None
        return None

    def _update_charging(self, inputs: Inputs) -> ChargerCommand | None:
        if inputs.surplus_power_w is None or inputs.charger_power_w is None:
            self.state = ControllerState.IDLE
            self._condition_since = None
            return ChargerCommand.TURN_OFF

        self._learn_charging_power(inputs.charger_power_w)
        if inputs.surplus_power_w < 0:
            if self._condition_since is None:
                self._condition_since = inputs.now
            elif inputs.now - self._condition_since >= self.config.stop_duration:
                self.state = ControllerState.IDLE
                self._condition_since = None
                return ChargerCommand.TURN_OFF
        else:
            self._condition_since = None
        return None

    def _update_calibration(self, inputs: Inputs) -> ChargerCommand | None:
        if inputs.charger_power_w is not None and (
            0 <= inputs.charger_power_w < self.config.full_power_threshold_w
        ):
            if self._condition_since is None:
                self._condition_since = inputs.now
            elif inputs.now - self._condition_since >= self.config.full_detection_duration:
                self.persisted.estimated_energy_wh = self.config.capacity_wh
                self.persisted.last_calibration = inputs.now
                self.persisted.requires_recalibration = False
                self.state = ControllerState.IDLE
                self._condition_since = None
                return ChargerCommand.TURN_OFF
        else:
            self._condition_since = None
        if inputs.charger_is_on is not True:
            return ChargerCommand.TURN_ON
        return None

    def _learn_charging_power(self, power_w: float) -> None:
        if not isfinite(power_w) or power_w < self.config.learning_min_power_w:
            return
        previous = self.persisted.expected_charging_power_w
        assert previous is not None
        alpha = self.config.learning_alpha
        self.persisted.expected_charging_power_w = previous + alpha * (power_w - previous)

    def _update_energy(self, inputs: Inputs) -> None:
        if not inputs.charger_available or self.state is ControllerState.DISCONNECTED:
            self.persisted.previous_charger_energy_kwh = inputs.charger_energy_kwh
            self.persisted.previous_load_energy_kwh = inputs.load_energy_kwh
            return

        charge_delta = self._positive_delta(
            inputs.charger_energy_kwh, self.persisted.previous_charger_energy_kwh
        )
        load_delta = self._positive_delta(
            inputs.load_energy_kwh, self.persisted.previous_load_energy_kwh
        )
        self.persisted.previous_charger_energy_kwh = inputs.charger_energy_kwh
        self.persisted.previous_load_energy_kwh = inputs.load_energy_kwh

        delta_wh = charge_delta * 1000 * self.config.charging_efficiency - load_delta * 1000
        self.persisted.estimated_energy_wh = min(
            self.config.capacity_wh,
            max(0.0, self.persisted.estimated_energy_wh + delta_wh),
        )

    @staticmethod
    def _positive_delta(current: float | None, previous: float | None) -> float:
        if current is None or previous is None or not isfinite(current) or not isfinite(previous):
            return 0.0
        delta = current - previous
        return delta if delta >= 0 else 0.0

    def _mark_periodic_calibration(self, now: datetime) -> None:
        last = self.persisted.last_calibration
        if last is None or now - last >= self.config.calibration_interval:
            self.persisted.requires_recalibration = True

    def _persistent_fingerprint(self) -> tuple[object, ...]:
        state = self.persisted
        return (
            state.estimated_energy_wh,
            state.expected_charging_power_w,
            state.last_calibration,
            state.previous_charger_energy_kwh,
            state.previous_load_energy_kwh,
            state.requires_recalibration,
        )


def _optional_float(value: object) -> float | None:
    """Convert a persisted optional numeric value."""
    return None if value is None else float(value)
