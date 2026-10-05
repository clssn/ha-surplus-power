# Surplus Power developer guide

## Design and safety

Business logic lives in `custom_components/surplus_power/controller.py` and does
not depend on Home Assistant. Its complete command vocabulary consists of
turning charging input on or off. Protected-load measurements cannot produce a
separate actuator command.

`custom_components/surplus_power/runtime.py` adapts Home Assistant state events,
storage, timers, and services to the controller. It serializes refreshes and
rejects configured actuator entity IDs outside the `switch` domain.

The config flow supports native reconfiguration so users can inspect and update
all six entity roles without removing the entry. Changing the charger switch
also updates the entry's unique ID.

The entity platforms are diagnostic views over the runtime. They do not contain
control logic.

## Local environment

Python dependencies and tools are managed by `uv`:

```shell
uv sync --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Equivalent shortcuts are available as `make sync`, `make test`, and `make
check`.

## Commit checks

Install and run the pre-commit-compatible hooks with `prek` through `uvx`:

```shell
uvx prek install
uvx prek run --all-files
```

The hooks verify that:

- `uv.lock` matches `pyproject.toml` whenever project metadata changes;
- Ruff static analysis passes;
- Ruff formatting is already applied;
- the unit and Home Assistant lifecycle tests pass.

The same commands are available as `make prek-install` and `make prek`.

## Commit messages

Write a brief, imperative subject that captures why the change is needed rather
than listing what files or code changed. Follow it with roughly three to six
high-level bullet points describing what the change accomplishes at an abstract
level. Keep implementation details out of the commit message.

## Tests

Pure controller tests cover probe admission, fast probe abort and cooldown,
normal and full-battery hysteresis, calibration, bulk-power observation, cumulative
energy accounting, disconnect grace and reconnect behavior, persistence, and
unavailable sensor failure modes. Home Assistant tests cover config-flow uniqueness,
setup/unload behavior, unit conversion, and the charger service-call boundary.

Keep timing tests deterministic by passing explicit timestamps to the controller
instead of sleeping.

## Deployment

Home Assistant loads custom integrations from
`<config directory>/custom_components/<domain>`. Home Assistant Core and many
add-ons expose the configuration directory as `/config`, making the common
in-environment path:

```text
/config/custom_components/surplus_power
```

Paths visible over SSH depend on the installation and SSH service. This project's
live system uses the standard Raspberry Pi Home Assistant OS image with
Supervisor and the Terminal & SSH App. That environment exposes the deployment
target as:

```text
root@homeassistant.local:/root/homeassistant/custom_components/surplus_power
```

`make deploy` runs lint and tests, then synchronizes only
`custom_components/surplus_power` to that project-specific default. Other
installations should override both variables, for example:

```shell
make deploy HA_HOST=user@example HA_COMPONENT_DIR=/config/custom_components/surplus_power
```

Python bytecode caches are excluded. The command does not restart Home
Assistant. Before restarting, run `ha core check` on the host. After restart,
inspect logs and controller diagnostics before any live switching test.

Never test by controlling protected-load power. Live commands must target only
the configured power-station charging-input switch.
