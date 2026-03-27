"""Shared test fixtures for the Emulated Hue integration tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.emulated_hue.const import (
    CONF_ENTITIES,
    CONF_ENTITY_NAME,
    CONF_LISTEN_PORT,
    DEFAULT_LISTEN_PORT,
    DOMAIN,
)

MOCK_ENTITIES: dict[str, dict[str, str]] = {
    "input_boolean.test_switch": {CONF_ENTITY_NAME: "Test Switch"},
    "light.living_room": {CONF_ENTITY_NAME: "Living Room"},
    "scene.movie_time": {CONF_ENTITY_NAME: "Movie Time"},
}

MOCK_HOST_IP = "192.168.1.100"
MOCK_BRIDGE_MAC = "00:17:88:01:00:64"
MOCK_BRIDGE_ID = "001788010064FFFE"


@pytest.fixture
def mock_config_entry() -> ConfigEntry:
    """Create a mock config entry for Emulated Hue."""
    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Emulated Hue",
        data={CONF_LISTEN_PORT: DEFAULT_LISTEN_PORT},
        options={CONF_ENTITIES: MOCK_ENTITIES},
        source="user",
        unique_id=DOMAIN,
    )
    return entry


@pytest.fixture
def mock_empty_config_entry() -> ConfigEntry:
    """Create a config entry with no entities configured."""
    return ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Emulated Hue",
        data={CONF_LISTEN_PORT: DEFAULT_LISTEN_PORT},
        options={CONF_ENTITIES: {}},
        source="user",
        unique_id=DOMAIN,
    )


@pytest.fixture
def patch_host_ip() -> Generator[None]:
    """Patch _get_host_ip to return a deterministic IP."""
    with patch(
        "custom_components.emulated_hue._get_host_ip",
        return_value=MOCK_HOST_IP,
    ):
        yield


@pytest.fixture
def patch_upnp() -> Generator[None]:
    """Patch SSDP responder creation to avoid real UDP sockets in tests."""
    mock_transport = AsyncMock()
    mock_transport.close = lambda: None

    async def mock_create(*args: Any, **kwargs: Any) -> tuple[Any, Any]:
        return mock_transport, AsyncMock()

    with patch(
        "custom_components.emulated_hue.create_upnp_responder",
        side_effect=mock_create,
    ):
        yield
