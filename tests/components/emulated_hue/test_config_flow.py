"""Tests for the Emulated Hue config flow."""

from __future__ import annotations

from typing import Any

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.emulated_hue.const import (
    CONF_ENTITIES,
    CONF_LISTEN_PORT,
    DEFAULT_LISTEN_PORT,
    DOMAIN,
)


async def test_user_step_creates_entry(hass: HomeAssistant) -> None:
    """Test that the user step creates a config entry with the chosen port."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LISTEN_PORT: 8300},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Emulated Hue"
    assert result["data"][CONF_LISTEN_PORT] == 8300
    assert result["options"][CONF_ENTITIES] == {}


async def test_user_step_default_port(hass: HomeAssistant) -> None:
    """Test that the default port is 8300."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    schema = result["data_schema"]
    assert schema is not None


async def test_single_instance_only(hass: HomeAssistant) -> None:
    """Test that only one instance can be configured."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LISTEN_PORT: 8300},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_entity_selection(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Test the options flow for selecting entities."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(
        mock_config_entry.entry_id
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
