"""Config-flow tests."""

from helpers import USER_INPUT
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant

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
