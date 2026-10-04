# Surplus Power user guide

## Safety boundary

Surplus Power controls only the configured power-station charging-input switch.
The protected-load power and energy entities are measurements only. The
integration never switches or interrupts the protected load.

When input data is missing or uncertain, the controller prefers not to charge.

## Installation

Copy `custom_components/surplus_power` into the Home Assistant configuration
directory as `custom_components/surplus_power`, then restart Home Assistant.
Home Assistant commonly exposes this as
`/config/custom_components/surplus_power`, but the host-visible path depends on
the installation type and SSH or container setup.

In Home Assistant, open **Settings → Devices & services → Add integration** and
select **Surplus Power**.

## Entity configuration

Select these six existing Home Assistant entities:

- site net grid-balance power—not raw solar generation—where positive values
  mean export and negative values mean grid import;
- power-station charging-input switch;
- charging-input instantaneous power;
- charging-input cumulative energy;
- protected-load instantaneous power, read only;
- protected-load cumulative energy, read only.

Double-check the charging switch selection. It is the integration's only
actuator.

To review or change these selections later, open **Settings → Devices &
services → Surplus Power**, open the integration entry's menu, and choose
**Reconfigure**. The form displays all current selections. The net grid entity
must report positive values for export and negative values for grid import; a
sensor reporting positive household consumption has the wrong polarity.
Changing charger or cumulative-energy measurements requires a fresh calibration;
correcting only the surplus or protected-load power selection does not.

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

While `IDLE`, the controller waits for a small configurable minimum surplus to
remain available for the configured start duration. It then enters `PROBING`
and deliberately turns charging on to measure the battery's actual demand.

During the probe, sustained grid import stops charging after the short probe
stop duration. An unsuccessful probe is followed by a configurable cooldown to
avoid repeated switching. If useful charging power is observed and there is no
grid import at the end of the probe, the controller enters `CHARGING`. Normal
charging stops after grid import lasts for the longer configured stop duration.

The controller owns the configured charger switch. Manually switching it off
while `PROBING` or `CHARGING` returns the controller to `IDLE`; an unexpectedly
on switch in `IDLE` is turned off. A short settling window allows Home Assistant
time to report a switch command before treating the reported state as an
override.

The last observed bulk charging power is retained as a diagnostic. It is learned
during probes, normal charging, and calibration, but it is not a startup
threshold. The controller keeps the useful peak from each charging session so
low end-of-charge taper readings do not replace it.

Full-charge detection also runs during probing and normal charging. If charging
power remains below the configured full threshold while the charging switch is
on, the controller anchors the battery estimate at 100% and turns charging off.

The battery estimate uses cumulative charging and protected-load energy. It
remains an estimate: charging efficiency, meter resets, AC bypass behavior, and
device removal can all affect accuracy.

## Disconnection and periodic calibration

If required charger entities become unavailable, the controller first waits for
the configured disconnect grace period and sends no charger commands. This
prevents brief entity restoration during a Home Assistant restart from forcing
calibration. If unavailability persists, it enters `DISCONNECTED` and requires a
new calibration. After the charger returns and remains available for the
configured stabilization duration, calibration starts before normal control
resumes.

Calibration is also forced when the previous successful calibration exceeds the
configured interval. The **Force calibration** button starts the same process
manually.

## Diagnostic entities

The integration exposes:

- estimated battery level;
- estimated battery energy;
- controller state;
- observed bulk charging power;
- last calibration time;
- calibration-due status;
- force-calibration button.

These entities report controller state; no additional automations are required.

## Options

Open the integration's **Configure** dialog to adjust nominal capacity, charging
efficiency, minimum surplus and duration before probing, probe duration, quick
probe-stop duration, probe cooldown, normal stop duration, full-detection
threshold and duration, periodic calibration interval, disconnect grace period,
and reconnect duration.

## Troubleshooting

- `CALIBRATING`: the battery model needs a full-charge anchor. Charging may run
  regardless of surplus.
- `PROBING`: charging is temporarily on so the controller can observe actual
  demand; sustained import causes a quick stop.
- `DISCONNECTED`: verify the configured charger switch and cumulative charger
  energy entities are available.
- Charging stops unexpectedly: check surplus and charging-power entity
  availability; missing feedback causes a safe stop.
- SOC appears inaccurate: allow calibration to complete and verify cumulative
  energy units are Wh or kWh.

Inspect Home Assistant logs for `surplus_power` when setup or entities fail.
