"""Config-flow tests."""

from helpers import USER_INPUT
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.surplus_power.const import CONF_CHARGER_SWITCH_ENTITY, DOMAIN


async def test_user_flow_creates_entry(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """All six entities are collected by the config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )
    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT
    assert result["result"].unique_id == USER_INPUT[CONF_CHARGER_SWITCH_ENTITY]


async def test_duplicate_charger_switch_is_rejected(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """One charger input switch cannot be controlled by two entries."""
    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}, data=USER_INPUT
    )
    assert first["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY

    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}, data=USER_INPUT
    )
    assert second["type"] is data_entry_flow.FlowResultType.ABORT
    assert second["reason"] == "already_configured"


async def test_reconfigure_shows_and_updates_selected_entities(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Existing entity selections are visible and editable in place."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Surplus Power",
        data=USER_INPUT,
        unique_id=USER_INPUT[CONF_CHARGER_SWITCH_ENTITY],
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["data_schema"]({}) == USER_INPUT

    updated = USER_INPUT | {
        "surplus_power_entity": "sensor.correctly_signed_surplus",
        CONF_CHARGER_SWITCH_ENTITY: "switch.replacement_charger_input",
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input=updated)

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == updated
    assert entry.unique_id == updated[CONF_CHARGER_SWITCH_ENTITY]
