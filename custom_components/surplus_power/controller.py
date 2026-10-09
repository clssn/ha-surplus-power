"""HA-independent surplus charging controller.

This module deliberately knows nothing about Home Assistant services or entity
IDs. It can request only charger input commands; the protected load is always
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
    RECOVERING = "recovering"
    IDLE = "idle"
    PROBING = "probing"
    CHARGING = "charging"
    FULL = "full"


class ChargerCommand(StrEnum):
    """The complete actuator vocabulary exposed by the controller."""

    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"


@dataclass(frozen=True, slots=True)
class ControllerConfig:
    """Controller tuning parameters."""

    capacity_wh: float = 1056.0
    charging_efficiency: float = 0.80
    minimum_probe_surplus_w: float = 50.0
    start_duration: timedelta = timedelta(seconds=60)
    probe_duration: timedelta = timedelta(seconds=60)
    probe_stop_duration: timedelta = timedelta(seconds=5)
    probe_cooldown: timedelta = timedelta(minutes=5)
    stop_duration: timedelta = timedelta(seconds=60)
    full_power_threshold_w: float = 10.0
    full_detection_duration: timedelta = timedelta(seconds=30)
    calibration_interval: timedelta = timedelta(days=7)
    disconnect_duration: timedelta = timedelta(seconds=60)
    reconnect_duration: timedelta = timedelta(seconds=30)
    load_outage_duration: timedelta = timedelta(seconds=60)
    load_recovery_duration: timedelta = timedelta(seconds=30)
    reserve_start_fraction: float = 0.20
    recovery_target_fraction: float = 0.30
    switch_transition_timeout: timedelta = timedelta(seconds=10)
    minimum_observed_charging_power_w: float = 50.0

    def __post_init__(self) -> None:
        if self.capacity_wh <= 0:
            raise ValueError("capacity_wh must be positive")
        if not 0 < self.charging_efficiency <= 1:
            raise ValueError("charging_efficiency must be in (0, 1]")
        if self.minimum_probe_surplus_w < 0:
            raise ValueError("minimum_probe_surplus_w must not be negative")
        for name, duration in (
            ("probe_duration", self.probe_duration),
            ("probe_stop_duration", self.probe_stop_duration),
            ("probe_cooldown", self.probe_cooldown),
        ):
            if duration <= timedelta(0):
                raise ValueError(f"{name} must be positive")
        if self.switch_transition_timeout <= timedelta(0):
            raise ValueError("switch_transition_timeout must be positive")
        if self.load_outage_duration <= timedelta(0):
            raise ValueError("load_outage_duration must be positive")
        if self.load_recovery_duration < timedelta(0):
            raise ValueError("load_recovery_duration must not be negative")
        if not 0 < self.reserve_start_fraction <= 1:
            raise ValueError("reserve_start_fraction must be in (0, 1]")
        if not self.reserve_start_fraction < self.recovery_target_fraction <= 1:
            raise ValueError("recovery_target_fraction must be above the reserve start")


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
    load_power_w: float | None = None
    load_energy_kwh: float | None = None


@dataclass(slots=True)
class PersistentState:
    """State suitable for integration-local persistence."""

    estimated_energy_wh: float = 0.0
    last_charging_power_w: float | None = None
    last_calibration: datetime | None = None
    previous_charger_energy_kwh: float | None = None
    previous_load_energy_kwh: float | None = None
    requires_recalibration: bool = True
    recovery_required: bool = False

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "estimated_energy_wh": self.estimated_energy_wh,
            "last_charging_power_w": self.last_charging_power_w,
            "last_calibration": (
                self.last_calibration.isoformat() if self.last_calibration is not None else None
            ),
            "previous_charger_energy_kwh": self.previous_charger_energy_kwh,
            "previous_load_energy_kwh": self.previous_load_energy_kwh,
            "requires_recalibration": self.requires_recalibration,
            "recovery_required": self.recovery_required,
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
            last_charging_power_w=_optional_float(data.get("last_charging_power_w")),
            last_calibration=last_calibration,
            previous_charger_energy_kwh=_optional_float(data.get("previous_charger_energy_kwh")),
            previous_load_energy_kwh=_optional_float(data.get("previous_load_energy_kwh")),
            requires_recalibration=bool(data.get("requires_recalibration", True)),
            recovery_required=bool(data.get("recovery_required", False)),
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
        if self.persisted.requires_recalibration:
            self.state = ControllerState.NEEDS_CALIBRATION
        elif self.persisted.recovery_required:
            self.state = ControllerState.RECOVERING
        else:
            self.state = ControllerState.IDLE
        self._condition_since: datetime | None = None
        self._unavailable_since: datetime | None = None
        self._available_since: datetime | None = None
        self._load_unavailable_since: datetime | None = None
        self._load_available_since: datetime | None = None
        self._switch_on_requested_at: datetime | None = None
        self._probe_started_at: datetime | None = None
        self._probe_cooldown_until: datetime | None = None
        self._full_power_since: datetime | None = None
        self._session_peak_power_w: float | None = None
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
        deadlines: list[datetime] = []
        if (
            self.state in {ControllerState.PROBING, ControllerState.CHARGING}
            and self._switch_on_requested_at is not None
        ):
            deadlines.append(self._switch_on_requested_at + self.config.switch_transition_timeout)
        if self.state is ControllerState.PROBING and self._probe_started_at is not None:
            deadlines.append(self._probe_started_at + self.config.probe_duration)
        if self._condition_since is not None:
            durations = {
                ControllerState.IDLE: self.config.start_duration,
                ControllerState.PROBING: self.config.probe_stop_duration,
                ControllerState.CHARGING: self.config.stop_duration,
                ControllerState.FULL: self.config.stop_duration,
            }
            duration = durations.get(self.state)
            if duration is not None:
                deadlines.append(self._condition_since + duration)
        if self._full_power_since is not None:
            deadlines.append(self._full_power_since + self.config.full_detection_duration)
        if self.state is ControllerState.DISCONNECTED and self._available_since is not None:
            deadlines.append(self._available_since + self.config.reconnect_duration)
        if self._unavailable_since is not None and self.state is not ControllerState.DISCONNECTED:
            deadlines.append(self._unavailable_since + self.config.disconnect_duration)
        if self._load_unavailable_since is not None and self.state not in {
            ControllerState.CALIBRATING,
            ControllerState.DISCONNECTED,
            ControllerState.RECOVERING,
        }:
            deadlines.append(self._load_unavailable_since + self.config.load_outage_duration)
        if self.state is ControllerState.RECOVERING and self._load_available_since is not None:
            deadlines.append(self._load_available_since + self.config.load_recovery_duration)
        if self.state is ControllerState.IDLE and self._probe_cooldown_until is not None:
            deadlines.append(self._probe_cooldown_until)
        if self.persisted.last_calibration is not None and not self.calibration_due:
            deadlines.append(self.persisted.last_calibration + self.config.calibration_interval)
        return min(deadlines) if deadlines else None

    def request_calibration(self) -> None:
        """Request calibration at the next input evaluation."""
        self.persisted.requires_recalibration = True
        self.persisted.recovery_required = False
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
            if self._unavailable_since is None:
                self._unavailable_since = inputs.now
            if (
                self.state is not ControllerState.DISCONNECTED
                and inputs.now - self._unavailable_since < self.config.disconnect_duration
            ):
                self._last_inputs = inputs
                return ControllerResult(
                    self.state,
                    None,
                    before != self._persistent_fingerprint(),
                )
            self.state = ControllerState.DISCONNECTED
            self.persisted.requires_recalibration = True
            self._available_since = None
            self._condition_since = None
            self._switch_on_requested_at = None
            self._reset_charge_session()
            self._last_inputs = inputs
            return ControllerResult(
                self.state,
                None,
                before != self._persistent_fingerprint(),
            )

        self._unavailable_since = None
        if self.state is ControllerState.DISCONNECTED:
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
            self._reset_charge_session()

        self._update_load_outage(inputs)
        self._start_reserve_recovery_if_needed()

        if self.state is ControllerState.NEEDS_CALIBRATION and inputs.charger_available:
            self.state = ControllerState.CALIBRATING
            self._condition_since = None
            self._begin_charge_session(inputs.now)
            if inputs.charger_is_on is not True:
                command = ChargerCommand.TURN_ON
        elif self.state is ControllerState.CALIBRATING:
            command = self._update_calibration(inputs)
        elif self.state is ControllerState.RECOVERING:
            command = self._update_recovering(inputs)
        elif self.state is ControllerState.IDLE:
            command = self._update_idle(inputs)
        elif self.state is ControllerState.PROBING:
            command = self._update_probing(inputs)
        elif self.state is ControllerState.CHARGING:
            command = self._update_charging(inputs)
        elif self.state is ControllerState.FULL:
            command = self._update_full(inputs)

        self._last_inputs = inputs
        return ControllerResult(self.state, command, before != self._persistent_fingerprint())

    def _update_idle(self, inputs: Inputs) -> ChargerCommand | None:
        self._switch_on_requested_at = None
        if inputs.charger_is_on is True:
            self._condition_since = None
            self._reset_charge_session()
            return ChargerCommand.TURN_OFF

        if self._probe_cooldown_until is not None and inputs.now < self._probe_cooldown_until:
            self._condition_since = None
            return None
        self._probe_cooldown_until = None

        if (
            inputs.surplus_power_w is not None
            and inputs.surplus_power_w >= self.config.minimum_probe_surplus_w
        ):
            if self._condition_since is None:
                self._condition_since = inputs.now
            elif inputs.now - self._condition_since >= self.config.start_duration:
                self.state = ControllerState.PROBING
                self._condition_since = None
                self._begin_charge_session(inputs.now)
                return ChargerCommand.TURN_ON
        else:
            self._condition_since = None
        return None

    def _update_probing(self, inputs: Inputs) -> ChargerCommand | None:
        if not self._switch_feedback_ready(inputs):
            return None
        if inputs.charger_is_on is False:
            return self._abort_probe(inputs.now, switch_is_on=False)
        if inputs.surplus_power_w is None or inputs.charger_power_w is None:
            return self._abort_probe(inputs.now, switch_is_on=True)

        self._observe_charging_power(inputs.charger_power_w)
        if self._full_power_detected(inputs):
            return self._complete_full_detection(inputs)

        if inputs.surplus_power_w < 0:
            if self._condition_since is None:
                self._condition_since = inputs.now
            elif inputs.now - self._condition_since >= self.config.probe_stop_duration:
                return self._abort_probe(inputs.now, switch_is_on=True)
        else:
            self._condition_since = None

        assert self._probe_started_at is not None
        if inputs.now - self._probe_started_at >= self.config.probe_duration:
            if self._session_peak_power_w is not None and inputs.surplus_power_w >= 0:
                self.state = ControllerState.CHARGING
                self._condition_since = None
                self._probe_started_at = None
                return None
            return self._abort_probe(inputs.now, switch_is_on=True)
        return None

    def _update_charging(self, inputs: Inputs) -> ChargerCommand | None:
        if not self._switch_feedback_ready(inputs):
            return None
        if inputs.charger_is_on is False:
            self.state = ControllerState.IDLE
            self._condition_since = None
            self._reset_charge_session()
            return None

        if inputs.surplus_power_w is None or inputs.charger_power_w is None:
            self.state = ControllerState.IDLE
            self._condition_since = None
            self._reset_charge_session()
            return ChargerCommand.TURN_OFF

        self._observe_charging_power(inputs.charger_power_w)
        if self._full_power_detected(inputs):
            return self._complete_full_detection(inputs)
        if inputs.surplus_power_w < 0:
            if self._condition_since is None:
                self._condition_since = inputs.now
            elif inputs.now - self._condition_since >= self.config.stop_duration:
                self.state = ControllerState.IDLE
                self._condition_since = None
                self._reset_charge_session()
                return ChargerCommand.TURN_OFF
        else:
            self._condition_since = None
        return None

    def _update_calibration(self, inputs: Inputs) -> ChargerCommand | None:
        if inputs.charger_power_w is not None:
            self._observe_charging_power(inputs.charger_power_w)
        if self._full_power_detected(inputs):
            return self._complete_full_detection(inputs)
        if inputs.charger_is_on is not True:
            return ChargerCommand.TURN_ON
        return None

    def _update_recovering(self, inputs: Inputs) -> ChargerCommand | None:
        """Restore a safe reserve after evidence that the battery was empty."""
        if inputs.charger_power_w is None:
            return ChargerCommand.TURN_OFF if inputs.charger_is_on is True else None
        self._observe_charging_power(inputs.charger_power_w)
        if self._full_power_detected(inputs):
            return self._complete_full_detection(inputs)
        if inputs.charger_is_on is not True:
            return ChargerCommand.TURN_ON

        target_wh = self.config.capacity_wh * self.config.recovery_target_fraction
        load_stable = (
            self._load_available_since is not None
            and inputs.now - self._load_available_since >= self.config.load_recovery_duration
        )
        if self.persisted.estimated_energy_wh < target_wh or not load_stable:
            return None

        self.persisted.recovery_required = False
        self._condition_since = None
        self._reset_charge_session()
        if inputs.surplus_power_w is not None and inputs.surplus_power_w >= 0:
            self.state = ControllerState.CHARGING
            self._observe_charging_power(inputs.charger_power_w)
            return None
        self.state = ControllerState.IDLE
        return ChargerCommand.TURN_OFF

    def _update_full(self, inputs: Inputs) -> ChargerCommand | None:
        if inputs.charger_is_on is False:
            self.state = ControllerState.IDLE
            self._condition_since = None
            return None
        if inputs.surplus_power_w is None or inputs.charger_power_w is None:
            self.state = ControllerState.IDLE
            self._condition_since = None
            return ChargerCommand.TURN_OFF

        self.persisted.estimated_energy_wh = self.config.capacity_wh
        if inputs.charger_power_w >= self.config.minimum_observed_charging_power_w:
            self.state = ControllerState.CHARGING
            self._condition_since = None
            self._session_peak_power_w = None
            self._observe_charging_power(inputs.charger_power_w)
            return None

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

    def _observe_charging_power(self, power_w: float) -> None:
        if not isfinite(power_w) or power_w < self.config.minimum_observed_charging_power_w:
            return
        if self._session_peak_power_w is None or power_w > self._session_peak_power_w:
            self._session_peak_power_w = power_w
            self.persisted.last_charging_power_w = power_w

    def _full_power_detected(self, inputs: Inputs) -> bool:
        power_w = inputs.charger_power_w
        if (
            inputs.charger_is_on is True
            and power_w is not None
            and 0 <= power_w < self.config.full_power_threshold_w
        ):
            if self._full_power_since is None:
                self._full_power_since = inputs.now
            return inputs.now - self._full_power_since >= self.config.full_detection_duration
        self._full_power_since = None
        return False

    def _complete_full_detection(self, inputs: Inputs) -> ChargerCommand | None:
        self.persisted.estimated_energy_wh = self.config.capacity_wh
        self.persisted.last_calibration = inputs.now
        self.persisted.requires_recalibration = False
        self.persisted.recovery_required = False
        self._condition_since = None
        self._probe_cooldown_until = None
        self._reset_charge_session()
        if inputs.surplus_power_w is not None and inputs.surplus_power_w >= 0:
            self.state = ControllerState.FULL
            return None
        self.state = ControllerState.IDLE
        return ChargerCommand.TURN_OFF

    def _switch_feedback_ready(self, inputs: Inputs) -> bool:
        if inputs.charger_is_on is True:
            self._switch_on_requested_at = None
            return True
        return not (
            inputs.charger_is_on is False
            and self._switch_on_requested_at is not None
            and inputs.now - self._switch_on_requested_at < self.config.switch_transition_timeout
        )

    def _begin_charge_session(self, now: datetime) -> None:
        self._switch_on_requested_at = now
        self._probe_started_at = now
        self._session_peak_power_w = None
        self._full_power_since = None

    def _reset_charge_session(self) -> None:
        self._switch_on_requested_at = None
        self._probe_started_at = None
        self._session_peak_power_w = None
        self._full_power_since = None

    def _abort_probe(self, now: datetime, *, switch_is_on: bool) -> ChargerCommand | None:
        self.state = ControllerState.IDLE
        self._condition_since = None
        self._probe_cooldown_until = now + self.config.probe_cooldown
        self._reset_charge_session()
        return ChargerCommand.TURN_OFF if switch_is_on else None

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

    def _update_load_outage(self, inputs: Inputs) -> None:
        """Detect a sustained loss of both battery-powered load measurements."""
        both_missing = inputs.load_power_w is None and inputs.load_energy_kwh is None
        both_available = inputs.load_power_w is not None and inputs.load_energy_kwh is not None

        if both_missing:
            self._load_available_since = None
            if self._load_unavailable_since is None:
                self._load_unavailable_since = inputs.now
            if (
                self.state is not ControllerState.CALIBRATING
                and inputs.now - self._load_unavailable_since >= self.config.load_outage_duration
                and self.state is not ControllerState.RECOVERING
            ):
                self.persisted.estimated_energy_wh = 0.0
                self.persisted.recovery_required = True
                self.state = ControllerState.RECOVERING
                self._condition_since = None
                self._reset_charge_session()
            return

        self._load_unavailable_since = None
        if both_available and self.state is ControllerState.RECOVERING:
            if self._load_available_since is None:
                self._load_available_since = inputs.now
        else:
            self._load_available_since = None

    def _start_reserve_recovery_if_needed(self) -> None:
        """Force charging before the protected load can lose battery power."""
        if self.state not in {
            ControllerState.IDLE,
            ControllerState.PROBING,
            ControllerState.CHARGING,
        }:
            return
        reserve_start_wh = self.config.capacity_wh * self.config.reserve_start_fraction
        if self.persisted.estimated_energy_wh > reserve_start_wh:
            return
        self.persisted.recovery_required = True
        self.state = ControllerState.RECOVERING
        self._condition_since = None
        self._reset_charge_session()

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
            state.last_charging_power_w,
            state.last_calibration,
            state.previous_charger_energy_kwh,
            state.previous_load_energy_kwh,
            state.requires_recalibration,
            state.recovery_required,
        )


def _optional_float(value: object) -> float | None:
    """Convert a persisted optional numeric value."""
    return None if value is None else float(value)
