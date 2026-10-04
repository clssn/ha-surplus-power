# Surplus Power user guide

## Safety boundary

Surplus Power controls only the configured power-station charging-input switch.
The ventilation power and energy entities are measurements only. The integration
never switches or interrupts ventilation power.

When input data is missing or uncertain, the controller prefers not to charge.

## Installation

Copy `custom_components/surplus_power` into the Home Assistant configuration
directory as `custom_components/surplus_power`, then restart Home Assistant.

In Home Assistant, open **Settings → Devices & services → Add integration** and
select **Surplus Power**.

## Entity configuration

Select these six existing Home Assistant entities:

- surplus/export power, where positive values mean export;
- power-station charging-input switch;
- charging-input instantaneous power;
- charging-input cumulative energy;
- ventilation instantaneous power, read only;
- ventilation cumulative energy, read only.

Double-check the charging switch selection. It is the integration's only
actuator.

## First start and calibration

A new installation has no trustworthy battery estimate, so it starts in
`CALIBRATING`. Calibration requests that the charging-input switch be on. If it
is already on, the integration leaves it on and continues observing charging
power.

When charging power remains below the full-detection threshold for the configured
duration, the controller considers the battery full. It sets estimated energy to
the nominal capacity, records the calibration time, turns charging input off,
and enters `IDLE`.

Calibration ignores surplus restrictions. Do not start initial or manual
calibration unless mains charging is acceptable until the battery becomes full.

## Normal operation

While `IDLE`, charging starts only after surplus continuously covers the expected
charging demand for the configured start duration. While `CHARGING`, it stops
after sustained grid import for the configured stop duration. Brief threshold
crossings do not switch the charger.

The expected charging demand begins at the configured fallback and is learned
from measured charging power. Low end-of-charge taper readings are ignored.

The battery estimate uses cumulative charging and ventilation energy. It remains
an estimate: charging efficiency, meter resets, AC bypass behavior, and device
removal can all affect accuracy.

## Disconnection and periodic calibration

If the charger is removed or required charger entities become unavailable, the
controller enters `DISCONNECTED`, sends no charger commands, and requires a new
calibration. After the charger returns and remains available for the configured
stabilization duration, calibration starts before normal control resumes.

Calibration is also forced when the previous successful calibration exceeds the
configured interval. The **Force calibration** button starts the same process
manually.

## Diagnostic entities

The integration exposes:

- estimated battery level;
- estimated battery energy;
- controller state;
- expected charging power;
- last calibration time;
- calibration-due status;
- force-calibration button.

These entities report controller state; no additional automations are required.

## Options

Open the integration's **Configure** dialog to adjust nominal capacity, charging
efficiency, initial expected demand, start and stop durations, full-detection
threshold and duration, periodic calibration interval, and reconnect duration.

## Troubleshooting

- `CALIBRATING`: the battery model needs a full-charge anchor. Charging may run
  regardless of surplus.
- `DISCONNECTED`: verify the configured charger switch and cumulative charger
  energy entities are available.
- Charging stops unexpectedly: check surplus and charging-power entity
  availability; missing feedback causes a safe stop.
- SOC appears inaccurate: allow calibration to complete and verify cumulative
  energy units are Wh or kWh.

Inspect Home Assistant logs for `surplus_power` when setup or entities fail.
