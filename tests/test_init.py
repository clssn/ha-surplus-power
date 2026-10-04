"""Integration setup and unload tests."""

from helpers import USER_INPUT
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.surplus_power.const import DOMAIN


async def test_setup_and_unload_while_charger_absent(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """An absent charger sets up safely and can be cleanly unloaded."""
    entry = MockConfigEntry(domain=DOMAIN, title="Surplus Power", data=USER_INPUT)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    runtime = hass.data[DOMAIN][entry.entry_id]
    assert runtime.controller.state.value == "disconnected"
    assert runtime.controller.persisted.requires_recalibration

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data[DOMAIN]
