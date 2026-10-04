We are implementing a Home Assistant custom integration for surplus-power charging of a portable Anker power station that supplies a central ventilation system.

The goal is to keep almost all logic inside one custom integration rather than spreading it across HA helpers, scripts, templates, and automations.

Existing Home Assistant entities:

- Surplus/export power:
  `sensor.sensor.balanced_power_production`
  Positive means excess production/export; negative means grid import.

- Power-station charging input switch:
  `switch.technikraum_batterie_eingang`

- Charging input instantaneous power:
  `sensor.technikraum_batterie_eingang_leistung`

- Charging input cumulative energy:
  `sensor.technikraum_batterie_eingang_energie`

- Ventilation instantaneous power:
  `sensor.technikraum_ventilation_power_supply_leistung`

- Ventilation cumulative energy:
  `sensor.technikraum_ventilation_power_supply_energie`

The Anker power station has no supported API.

Nominal battery capacity:
- 1056 Wh / 1.056 kWh

Primary safety invariant:
- The integration must NEVER switch off or otherwise control the ventilation power supply.
- It may only control `switch.technikraum_batterie_eingang`.
- Sudden removal of power from the ventilation may damage the fans/bearings.

Required behavior:

1. Normal surplus charging

When idle:
- Start charging only when surplus is greater than or equal to the expected charging power continuously for 60 seconds.
- Expected charging power has an initial configurable fallback value.
- Once charging has started, learn/update expected charging power from `sensor.technikraum_batterie_eingang_leistung`.
- Do not let tapering near full charge drag the learned expected charging power down to near zero.

When charging:
- Stop charging if `sensor.sensor.balanced_power_production < 0` continuously for 60 seconds.
- Thus startup requires enough surplus to cover expected charger demand, but continuation merely requires no sustained grid import.

Use asynchronous timers/callbacks rather than polling.

2. Battery energy/SOC model

Maintain a persistent estimated battery energy in Wh.

Model energy using cumulative energy sensor deltas where possible:

battery_delta =
    charging_input_delta * charging_efficiency
    - ventilation_energy_delta

Initial charging efficiency:
- 0.80
- configurable

Clamp estimated battery energy to `[0, capacity_wh]`.

Expose estimated SOC as:
`estimated_energy_wh / capacity_wh * 100`.

Treat meter resets and negative cumulative-energy deltas defensively.

Important:
Investigate whether the Anker uses AC bypass/pass-through while charging and supplying the ventilation simultaneously. Structure the model so this can be adjusted later if charger input energy includes direct load supply as well as battery charging.

3. Full-charge calibration

The battery model is recalibrated at 100%.

When calibration is active:
- Force the charging switch ON regardless of surplus.
- Observe charger input power.
- If charger input power remains below a configurable near-zero threshold, initially 10 W, continuously for 30 seconds, consider the battery fully charged.

Then:
- set estimated battery energy = capacity_wh
- store calibration timestamp
- stop calibration
- switch charger input OFF
- resume normal control

4. Periodic forced calibration

If last full-charge calibration is older than 7 days:
- force a calibration cycle
- once started, keep charging until full-charge detection succeeds

The 7-day interval should be configurable.

5. Power station removed for camping

Sometimes the power station is physically removed.
In that situation the charging device/entity becomes unavailable, and the ventilation is connected directly to mains manually.

If the charger switch or required charger entities become unavailable:
- enter a DISCONNECTED state
- issue no switch commands
- stop trusting/updating the battery model as though the battery were still connected
- remember that recalibration is required when it returns

When the device becomes available again:
- wait for availability to be stable, initially 30 seconds
- enter calibration
- obtain a fresh 100% calibration before returning to normal surplus charging

6. Failure behavior

Fail safely with respect to charging:
- if surplus data disappears during normal charging, stop charging
- if charger-power feedback disappears during normal charging, stop charging
- never take any action that interrupts ventilation power

7. Suggested internal controller states

- DISCONNECTED
- NEEDS_CALIBRATION
- CALIBRATING
- IDLE
- CHARGING

A dedicated controller class should own the state machine and business logic.

8. Persistence

Use Home Assistant integration-local persistent storage, e.g. `homeassistant.helpers.storage.Store`, for runtime/model state such as:

- estimated_energy_wh
- last_calibration
- expected_charging_power_w
- previous cumulative charger-energy reading
- previous cumulative load-energy reading
- whether a reconnect calibration is required

Do not create HA input helpers just to persist internal controller state.

9. Integration configuration

Use a normal Home Assistant config entry/config flow.

Configuration/options should include at least:

- entity IDs for all six source/control entities
- nominal capacity, default 1056 Wh
- initial expected charger power
- charging efficiency, default 0.80
- start-condition duration, default 60 s
- stop-condition duration, default 60 s
- full-charge power threshold, default 10 W
- full-charge detection duration, default 30 s
- forced calibration interval, default 7 days
- reconnect stabilization duration, default 30 s

Prefer an Options Flow for tunables instead of exposing lots of `number` helpers.

10. HA entities exposed by the integration

Initially expose approximately:

- estimated battery level (%)
- estimated battery energy (Wh)
- controller state
- learned/expected charging power
- last calibration timestamp
- calibration-due binary sensor
- manual force-calibration button

Keep these mostly diagnostic. The state machine itself must not depend on users wiring together these entities with automations.

11. Architecture

Suggested package:

custom_components/surplus_energy_controller/
    __init__.py
    manifest.json
    config_flow.py
    const.py
    controller.py
    sensor.py
    binary_sensor.py
    button.py
    strings.json
    translations/en.json

The controller should subscribe to state changes of the relevant HA entities. Avoid polling and avoid DataUpdateCoordinator unless it provides a concrete benefit.

12. Tests

Before live deployment, implement focused unit tests for at least:

- start after sustained surplus
- short surplus spike does not start charging
- stop after sustained import
- short import spike does not stop charging
- expected charging power learning
- low tapering power does not corrupt learned expected charging power
- charging energy increases SOC
- ventilation use decreases SOC
- cumulative energy sensor reset
- full-charge calibration
- periodic calibration due
- disconnected state
- reconnect requires recalibration
- HA restart with persisted state
- missing surplus data while charging
- missing charger power while charging
- no code path can control a ventilation switch

Please start by scaffolding the integration and unit-test setup, then implement the controller state machine independently enough that most behavior can be tested without a running HA instance.
