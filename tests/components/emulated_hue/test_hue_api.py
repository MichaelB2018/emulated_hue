"""Tests for the Hue API server."""

from __future__ import annotations

import json
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, State

from custom_components.emulated_hue.const import CONF_ENTITY_NAME
from custom_components.emulated_hue.hue_api import HueAPI

from .conftest import MOCK_BRIDGE_ID, MOCK_BRIDGE_MAC, MOCK_HOST_IP


def _create_hue_api(hass: HomeAssistant) -> HueAPI:
    """Create a HueAPI instance for testing."""
    api = HueAPI(
        hass=hass,
        bridge_id=MOCK_BRIDGE_ID,
        bridge_mac=MOCK_BRIDGE_MAC,
        host_ip=MOCK_HOST_IP,
        listen_port=8300,
    )
    api.update_entities(
        {
            "input_boolean.test_switch": {CONF_ENTITY_NAME: "Test Switch"},
            "scene.test_scene": {CONF_ENTITY_NAME: "Test Scene"},
        }
    )
    return api


@pytest.fixture
async def hue_client(hass: HomeAssistant, aiohttp_client) -> TestClient:
    """Create a test client for the Hue API."""
    # Set up mock entity states
    hass.states.async_set("input_boolean.test_switch", STATE_ON, {"friendly_name": "Test Switch"})
    hass.states.async_set("scene.test_scene", STATE_OFF, {"friendly_name": "Test Scene"})

    api = _create_hue_api(hass)
    app = api.create_app()
    return await aiohttp_client(app)


async def test_description_xml(hue_client: TestClient) -> None:
    """Test GET /description.xml returns valid XML."""
    resp = await hue_client.get("/description.xml")
    assert resp.status == 200
    text = await resp.text()
    assert "urn:schemas-upnp-org:device:Basic:1" in text
    assert MOCK_HOST_IP in text
    assert MOCK_BRIDGE_MAC.replace(":", "") in text
    assert resp.content_type == "application/xml"


async def test_registration(hue_client: TestClient) -> None:
    """Test POST /api returns a username."""
    resp = await hue_client.post(
        "/api",
        json={"devicetype": "alexa#echo"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 1
    assert "success" in data[0]
    assert "username" in data[0]["success"]
    username = data[0]["success"]["username"]
    assert len(username) > 0


async def test_lights_list(hue_client: TestClient) -> None:
    """Test GET /api/{username}/lights returns all configured lights."""
    resp = await hue_client.get("/api/testuser/lights")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 2

    # Lights should be keyed by sequential string IDs
    assert "1" in data
    assert "2" in data

    # Check one of the lights has the correct name
    names = {data[k]["name"] for k in data}
    assert "Test Switch" in names
    assert "Test Scene" in names


async def test_single_light(hue_client: TestClient) -> None:
    """Test GET /api/{username}/lights/{id} returns a single light."""
    resp = await hue_client.get("/api/testuser/lights/1")
    assert resp.status == 200
    data = await resp.json()
    assert "state" in data
    assert "name" in data
    assert data["type"] == "Dimmable light"
    assert "uniqueid" in data


async def test_single_light_not_found(hue_client: TestClient) -> None:
    """Test GET /api/{username}/lights/{id} with invalid ID returns error."""
    resp = await hue_client.get("/api/testuser/lights/999")
    assert resp.status == 404
    data = await resp.json()
    assert data[0]["error"]["type"] == 3


async def test_light_state_on(
    hass: HomeAssistant,
    hue_client: TestClient,
) -> None:
    """Test PUT .../state with on=true calls turn_on service."""
    calls: list[dict[str, Any]] = []

    async def mock_service_call(
        domain: str, service: str, service_data: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        calls.append({"domain": domain, "service": service, "data": service_data})

    hass.services.async_call = mock_service_call  # type: ignore[assignment]

    resp = await hue_client.put(
        "/api/testuser/lights/1/state",
        json={"on": True},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data[0]["success"]

    assert len(calls) == 1
    assert calls[0]["service"] == "turn_on"


async def test_light_state_off(
    hass: HomeAssistant,
    hue_client: TestClient,
) -> None:
    """Test PUT .../state with on=false calls turn_off service."""
    calls: list[dict[str, Any]] = []

    async def mock_service_call(
        domain: str, service: str, service_data: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        calls.append({"domain": domain, "service": service, "data": service_data})

    hass.services.async_call = mock_service_call  # type: ignore[assignment]

    resp = await hue_client.put(
        "/api/testuser/lights/1/state",
        json={"on": False},
    )
    assert resp.status == 200

    assert len(calls) == 1
    assert calls[0]["service"] == "turn_off"


async def test_scene_off_is_noop(
    hass: HomeAssistant,
    hue_client: TestClient,
) -> None:
    """Test that turning off a scene is a no-op (scenes are on-only)."""
    calls: list[dict[str, Any]] = []

    async def mock_service_call(
        domain: str, service: str, service_data: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        calls.append({"domain": domain, "service": service, "data": service_data})

    hass.services.async_call = mock_service_call  # type: ignore[assignment]

    # Find the scene light ID (it's sorted alphabetically, so scene comes after input_boolean)
    resp = await hue_client.get("/api/testuser/lights")
    data = await resp.json()
    scene_id = None
    for lid, ldata in data.items():
        if ldata["name"] == "Test Scene":
            scene_id = lid
            break
    assert scene_id is not None

    resp = await hue_client.put(
        f"/api/testuser/lights/{scene_id}/state",
        json={"on": False},
    )
    assert resp.status == 200
    # No service call should have been made for scene off
    assert len(calls) == 0


async def test_full_state(hue_client: TestClient) -> None:
    """Test GET /api/{username} returns full state dump."""
    resp = await hue_client.get("/api/testuser")
    assert resp.status == 200
    data = await resp.json()
    assert "lights" in data
    assert "config" in data
    assert "groups" in data
    assert len(data["lights"]) == 2


async def test_config_endpoint(hue_client: TestClient) -> None:
    """Test GET /api/{username}/config returns bridge config."""
    resp = await hue_client.get("/api/testuser/config")
    assert resp.status == 200
    data = await resp.json()
    assert data["modelid"] == "BSB002"
    assert data["bridgeid"] == MOCK_BRIDGE_ID
    assert data["mac"] == MOCK_BRIDGE_MAC


async def test_empty_endpoints(hue_client: TestClient) -> None:
    """Test that unsupported endpoints return empty dicts."""
    for path in [
        "/api/testuser/groups",
        "/api/testuser/schedules",
        "/api/testuser/scenes",
        "/api/testuser/rules",
        "/api/testuser/sensors",
        "/api/testuser/resourcelinks",
    ]:
        resp = await hue_client.get(path)
        assert resp.status == 200
        data = await resp.json()
        assert data == {}


async def test_invalid_json_body(hue_client: TestClient) -> None:
    """Test PUT with invalid JSON returns error."""
    resp = await hue_client.put(
        "/api/testuser/lights/1/state",
        data=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 400


async def test_light_on_state_reflected(
    hass: HomeAssistant,
    hue_client: TestClient,
) -> None:
    """Test that a light's on state reflects the entity state."""
    # input_boolean.test_switch is STATE_ON in setup
    resp = await hue_client.get("/api/testuser/lights")
    data = await resp.json()
    # Find the input_boolean light
    for lid, ldata in data.items():
        if ldata["name"] == "Test Switch":
            assert ldata["state"]["on"] is True
            assert ldata["state"]["bri"] == 254
            break

    # Change state to off
    hass.states.async_set("input_boolean.test_switch", STATE_OFF)
    resp = await hue_client.get("/api/testuser/lights")
    data = await resp.json()
    for lid, ldata in data.items():
        if ldata["name"] == "Test Switch":
            assert ldata["state"]["on"] is False
            assert ldata["state"]["bri"] == 0
            break
