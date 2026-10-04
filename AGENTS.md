# AGENTS.md

## Project purpose

This repository contains a Home Assistant custom integration for controlling surplus-energy charging of a portable battery/power station.

The first use case is a portable power station supplying a protected critical load.

The architecture should remain suitable for later generalization to other flexible electrical consumers, especially EV charging.

## Critical safety invariant

The integration MUST NEVER disconnect, switch, or otherwise control power to the protected load.

The only controlled actuator in the initial implementation is:

the charger-input switch selected in the config entry

This switch controls charging input to the power station.

The protected load is safety-critical for this project. Loss of charging or inaccurate SOC estimation is acceptable. Cutting load power is not.

When uncertain, prefer disabling charging over taking any action affecting the load.

## Design philosophy

Keep control logic centralized in Python.

Do not spread the implementation across:
- HA automations
- input helpers
- template sensors
- scripts

unless there is a very strong architectural reason.

Home Assistant should primarily provide:
- source sensor states
- one charger switch
- configuration
- diagnostic entities

The custom integration owns:
- control state
- hysteresis
- timers
- SOC estimation
- calibration
- reconnect handling
- persistence

## Required entity roles

Surplus power:

configured surplus-power sensor

Positive means export/surplus.

Charging switch:

configured charger-input switch

Charging power:

configured charger-power sensor

Charging cumulative energy:

configured cumulative charger-energy sensor

Protected-load power:

configured protected-load power sensor

Protected-load cumulative energy:

configured cumulative protected-load energy sensor

## Battery assumptions

Nominal capacity and charging efficiency must both be configurable. Do not
encode installation-specific values in documentation or entity examples.

The SOC estimate is approximate and is periodically anchored by detecting a physically full battery.

## Controller states

Prefer an explicit state machine:

- `DISCONNECTED`
- `NEEDS_CALIBRATION`
- `CALIBRATING`
- `IDLE`
- `CHARGING`

Avoid encoding important state implicitly through combinations of booleans.

## Normal charging rules

Start charging only when:

`surplus >= expected_charging_power`

continuously for the configured startup duration, initially 60 seconds.

Stop charging when:

`surplus < 0`

continuously for the configured stop duration, initially 60 seconds.

Short threshold crossings must not trigger switching.

## Expected charging-power learning

Maintain a persistent estimate of charger demand.

Start from a configurable initial value.

Learn from measured charging power once charging is established.

Use smoothing.

Do not allow end-of-charge tapering or near-zero measurements to collapse the learned expected charging power.

## Battery model

Prefer cumulative energy measurements over integration of instantaneous power.

Conceptually:

`battery_delta = charge_energy_delta * efficiency - load_energy_delta`

Clamp estimated battery energy to `[0, nominal_capacity]`.

Be robust against:
- sensor resets
- unknown/unavailable values
- HA restart
- stale previous readings

Do not silently interpret negative cumulative-energy deltas as real energy flow.

The power station may perform AC bypass/pass-through while simultaneously charging and powering the load. Keep this part of the model isolated enough to change later if measurements show that simple accounting is inaccurate.

## Full-charge calibration

During calibration:
- force charger input ON
- ignore surplus restrictions
- observe charger input power

When charger input power remains below the configured full-detection threshold, initially 10 W, for the configured duration, initially 30 seconds:

- set battery estimate to nominal capacity
- update last calibration timestamp
- finish calibration
- switch charger input OFF
- return to normal operation

## Forced calibration

If the previous successful calibration is older than the configured interval, initially 7 days, perform a forced calibration.

Once a forced calibration starts, continue until full detection succeeds unless the charger becomes unavailable.

## Disconnect/reconnect behavior

The power station is sometimes physically removed.

If required charger entities become unavailable:
- enter `DISCONNECTED`
- stop issuing charger commands
- mark the model as requiring recalibration

After the charger becomes available again:
- require stable availability for a configurable interval, initially 30 seconds
- calibrate before normal operation resumes

Do not assume the battery retained the previous SOC while disconnected.

## Failure policy

Prefer false negatives over false positives for charging.

Examples:

If surplus data becomes unavailable while charging:
- stop charging

If charger power feedback becomes unavailable while charging:
- stop charging

If protected-load measurement becomes unavailable:
- SOC estimation may become uncertain
- NEVER react by interrupting protected-load power

## Persistence

Use Home Assistant `Store` or the equivalent integration-local persistence mechanism.

Do not create HA input helpers merely to persist internal implementation details.

Persist enough information to restore sensible behavior after HA restart.

## HA architecture

Prefer:
- config entries
- config flow
- options flow
- event-driven state listeners
- asynchronous timers/callbacks

Avoid polling unless necessary.

Avoid `DataUpdateCoordinator` unless there is a concrete reason for it.

Keep Home Assistant entity classes thin.

Most business logic belongs in `controller.py`.

## Testing

The controller should be structured so that core behavior is testable without a live HA installation.

Use deterministic tests for timing behavior where possible.

Important test cases include:

- sustained surplus starts charging
- transient surplus does not
- sustained import stops charging
- transient import does not
- learned charger demand
- tapering does not poison learned charger demand
- charging increases estimated stored energy
- protected-load consumption decreases it
- cumulative meter reset
- calibration reaches 100%
- weekly calibration
- disconnect
- reconnect calibration
- persistence across restart
- sensor unavailability
- no code path can control protected-load power

## Live development

Development is done from VS Code with SSH access to the Home Assistant installation.

Preferred workflow:

1. run unit tests locally
2. copy/sync the custom component to HA
3. restart or reload HA as appropriate
4. inspect integration logs and entity state
5. make small controlled live tests
6. return fixes to unit-tested code

Live testing must not compromise the protected-load safety invariant.

This project's live system uses the standard Raspberry Pi Home Assistant OS
image with Supervisor and the Terminal & SSH App. In that SSH environment,
access the installation with `ssh root@homeassistant.local` and deploy to
`/root/homeassistant/custom_components/surplus_power`.

That remote path is environment-specific. Home Assistant's portable rule is
`<config directory>/custom_components/<domain>`; `/config/custom_components` is
the common path as seen by Home Assistant Core and many add-ons. Do not assume
the project's SSH path applies to other installation types. Keep host and target
paths overridable in deployment tooling.

## Future generalization

Do not over-generalize prematurely.

However, keep the surplus decision logic conceptually distinct from the power-station battery model.

A future controllable consumer, e.g. an EV charger, may have:
- variable charging power
- minimum charging current
- several controllable power levels
- different priorities
- no battery-SOC estimation requirement

Design interfaces so this evolution does not require rewriting the entire controller.

## Commit messages

Use a brief, imperative subject that captures why the change is needed rather
than merely listing what changed.

Add roughly three to six high-level bullet points in the body describing what
the change accomplishes at an abstract level. Avoid implementation-level detail.
For unusually broad changes such as the initial project commit, a few additional
bullets are acceptable.
