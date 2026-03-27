"""Hue bridge REST API server for the Emulated Hue integration.

Implements the Philips Hue API endpoints that Alexa and other Hue clients
use for device discovery and control. Only on/off is supported.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from aiohttp import web

from homeassistant.const import (
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
)
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ENTITIES,
    CONF_ENTITY_NAME,
    HUE_API_VERSION,
    HUE_DATASTORE_VERSION,
    HUE_MANUFACTURER,
    HUE_MODEL_ID,
    HUE_SW_VERSION,
)
from .store import ActivityTracker

_LOGGER = logging.getLogger(__name__)


class HueAPI:
    """Hue bridge REST API handler."""

    def __init__(
        self,
        hass: HomeAssistant,
        bridge_id: str,
        bridge_mac: str,
        host_ip: str,
        listen_port: int,
        advertise_port: int | None = None,
        activity_tracker: ActivityTracker | None = None,
    ) -> None:
        """Initialise the Hue API server."""
        self.hass = hass
        self.bridge_id = bridge_id
        self.bridge_mac = bridge_mac
        self.host_ip = host_ip
        self.listen_port = listen_port
        self.advertise_port = advertise_port or listen_port
        self.activity_tracker = activity_tracker
        self._entities: dict[str, dict[str, str]] = {}
        self._entity_id_to_light_id: dict[str, int] = {}
        self._light_id_to_entity_id: dict[int, str] = {}

    def update_entities(self, entities: dict[str, dict[str, str]]) -> None:
        """Update the entity-to-light mapping.

        Called when options change without requiring a restart.
        """
        self._entities = dict(entities)
        self._entity_id_to_light_id.clear()
        self._light_id_to_entity_id.clear()

        for idx, entity_id in enumerate(sorted(entities.keys()), start=1):
            self._entity_id_to_light_id[entity_id] = idx
            self._light_id_to_entity_id[idx] = entity_id

    def create_app(self) -> web.Application:
        """Create the aiohttp application with Hue API routes."""
        app = web.Application()
        app.router.add_get("/description.xml", self.handle_description)
        app.router.add_post("/api", self.handle_registration)
        app.router.add_get("/api/{username}", self.handle_full_state)
        app.router.add_get("/api/{username}/lights", self.handle_lights)
        app.router.add_get(
            "/api/{username}/lights/{light_id}", self.handle_light
        )
        app.router.add_put(
            "/api/{username}/lights/{light_id}/state",
            self.handle_light_state,
        )
        app.router.add_get("/api/{username}/config", self.handle_config)
        app.router.add_get("/api/{username}/groups", self.handle_empty)
        app.router.add_get("/api/{username}/schedules", self.handle_empty)
        app.router.add_get("/api/{username}/scenes", self.handle_empty)
        app.router.add_get("/api/{username}/rules", self.handle_empty)
        app.router.add_get("/api/{username}/sensors", self.handle_empty)
        app.router.add_get(
            "/api/{username}/resourcelinks", self.handle_empty
        )
        return app

    # ------------------------------------------------------------------
    # UPnP description.xml
    # ------------------------------------------------------------------

    async def handle_description(self, request: web.Request) -> web.Response:
        """Serve the UPnP bridge description XML."""
        xml = self._build_description_xml()
        return web.Response(text=xml, content_type="application/xml")

    def _build_description_xml(self) -> str:
        """Build the UPnP description XML document."""
        serial = self.bridge_mac.replace(':', '')
        return (
            '<?xml version="1.0" encoding="UTF-8" ?>\n'
            '<root xmlns="urn:schemas-upnp-org:device-1-0">\n'
            "<specVersion><major>1</major><minor>0</minor></specVersion>\n"
            f"<URLBase>http://{self.host_ip}:{self.advertise_port}/</URLBase>\n"
            "<device>\n"
            "<deviceType>urn:schemas-upnp-org:device:Basic:1</deviceType>\n"
            f"<friendlyName>Philips hue ({self.host_ip})</friendlyName>\n"
            f"<manufacturer>{HUE_MANUFACTURER}</manufacturer>\n"
            "<manufacturerURL>http://www.philips.com</manufacturerURL>\n"
            "<modelDescription>Philips hue Personal Wireless Lighting</modelDescription>\n"
            "<modelName>Philips hue bridge 2015</modelName>\n"
            f"<modelNumber>{HUE_MODEL_ID}</modelNumber>\n"
            "<modelURL>http://www.philips.com/hue</modelURL>\n"
            f"<serialNumber>{serial}</serialNumber>\n"
            f"<UDN>uuid:2f402f80-da50-11e1-9b23-{serial}</UDN>\n"
            "<presentationURL>index.html</presentationURL>\n"
            "</device>\n"
            "</root>"
        )

    # ------------------------------------------------------------------
    # POST /api — User registration
    # ------------------------------------------------------------------

    async def handle_registration(self, request: web.Request) -> web.Response:
        """Handle Hue user registration (POST /api).

        Alexa sends this to create an API key. We accept any request and
        return a deterministic username.
        """
        try:
            body = await request.json()
        except Exception:
            body = {}
        _LOGGER.info("Hue API: new device registration from %s", request.remote)
        username = f"ha{self.bridge_mac.replace(':', '')}"
        resp: dict[str, Any] = {"username": username}
        # Return clientkey if requested (newer Hue Entertainment API)
        if body.get("generateclientkey"):
            resp["clientkey"] = username.upper() + "A1B2C3D4E5F6"
        return web.json_response(
            [{"success": resp}],
        )

    # ------------------------------------------------------------------
    # GET /api/{username} — Full bridge state
    # ------------------------------------------------------------------

    async def handle_full_state(self, request: web.Request) -> web.Response:
        """Return full bridge state dump."""
        self._record_all_discovered()
        return web.json_response(
            {
                "lights": self._build_lights_dict(),
                "groups": {},
                "config": self._build_config_dict(),
                "schedules": {},
                "scenes": {},
                "rules": {},
                "sensors": {},
                "resourcelinks": {},
            }
        )

    # ------------------------------------------------------------------
    # GET /api/{username}/lights — List all lights
    # ------------------------------------------------------------------

    async def handle_lights(self, request: web.Request) -> web.Response:
        """Return all lights (exposed entities)."""
        self._record_all_discovered()
        return web.json_response(self._build_lights_dict())

    # ------------------------------------------------------------------
    # GET /api/{username}/lights/{light_id} — Single light
    # ------------------------------------------------------------------

    async def handle_light(self, request: web.Request) -> web.Response:
        """Return a single light by its Hue ID."""
        try:
            light_id = int(request.match_info["light_id"])
        except (ValueError, KeyError):
            return self._error_response(
                3, "resource not available", HTTPStatus.NOT_FOUND
            )

        entity_id = self._light_id_to_entity_id.get(light_id)
        if entity_id is None:
            return self._error_response(
                3, "resource not available", HTTPStatus.NOT_FOUND
            )

        light_data = self._build_light_dict(entity_id, light_id)
        return web.json_response(light_data)

    # ------------------------------------------------------------------
    # PUT /api/{username}/lights/{light_id}/state — Control a light
    # ------------------------------------------------------------------

    async def handle_light_state(
        self, request: web.Request
    ) -> web.Response:
        """Handle on/off state change for a light."""
        try:
            light_id = int(request.match_info["light_id"])
        except (ValueError, KeyError):
            return self._error_response(
                3, "resource not available", HTTPStatus.NOT_FOUND
            )

        entity_id = self._light_id_to_entity_id.get(light_id)
        if entity_id is None:
            return self._error_response(
                3, "resource not available", HTTPStatus.NOT_FOUND
            )

        try:
            body = await request.json()
        except Exception:
            return self._error_response(
                2, "body contains invalid JSON", HTTPStatus.BAD_REQUEST
            )

        is_on: bool = body.get("on", False)
        service = SERVICE_TURN_ON if is_on else SERVICE_TURN_OFF
        domain = entity_id.split(".")[0]

        # Scenes only support turn_on
        if domain == "scene":
            if is_on:
                await self.hass.services.async_call(
                    "scene", SERVICE_TURN_ON, {"entity_id": entity_id}
                )
            # For scenes, "off" is a no-op but we still respond success
        else:
            await self.hass.services.async_call(
                "homeassistant", service, {"entity_id": entity_id}
            )

        if self.activity_tracker is not None:
            self.activity_tracker.record_control(entity_id)
            self.hass.async_create_task(self.activity_tracker.async_save())

        _LOGGER.info(
            "Hue light %s (%s): %s", light_id, entity_id, service
        )

        result = [
            {"success": {f"/lights/{light_id}/state/on": is_on}},
        ]
        return web.json_response(result)

    # ------------------------------------------------------------------
    # GET /api/{username}/config — Bridge configuration
    # ------------------------------------------------------------------

    async def handle_config(self, request: web.Request) -> web.Response:
        """Return the bridge configuration."""
        return web.json_response(self._build_config_dict())

    # ------------------------------------------------------------------
    # Empty resource endpoints
    # ------------------------------------------------------------------

    async def handle_empty(self, request: web.Request) -> web.Response:
        """Return an empty dict for unsupported resource types."""
        return web.json_response({})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_all_discovered(self) -> None:
        """Mark every exposed entity as discovered."""
        if self.activity_tracker is not None:
            for entity_id in self._entity_id_to_light_id:
                self.activity_tracker.record_discovery(entity_id)
            self.hass.async_create_task(self.activity_tracker.async_save())

    def _build_lights_dict(self) -> dict[str, dict[str, Any]]:
        """Build the full lights dictionary."""
        lights: dict[str, dict[str, Any]] = {}
        for entity_id, light_id in self._entity_id_to_light_id.items():
            lights[str(light_id)] = self._build_light_dict(
                entity_id, light_id
            )
        return lights

    def _build_light_dict(
        self, entity_id: str, light_id: int
    ) -> dict[str, Any]:
        """Build the Hue light representation for a single entity."""
        entity_conf = self._entities.get(entity_id, {})
        name = entity_conf.get(CONF_ENTITY_NAME, "")

        if not name:
            state_obj = self.hass.states.get(entity_id)
            name = (
                state_obj.attributes.get("friendly_name", entity_id)
                if state_obj
                else entity_id
            )

        # Determine on/off state
        state_obj = self.hass.states.get(entity_id)
        is_on = state_obj is not None and state_obj.state == STATE_ON

        return {
            "state": {
                "on": is_on,
                "bri": 254 if is_on else 0,
                "hue": 0,
                "sat": 0,
                "effect": "none",
                "xy": [0.0, 0.0],
                "ct": 0,
                "alert": "none",
                "colormode": "hs",
                "mode": "homeautomation",
                "reachable": state_obj is not None,
            },
            "swupdate": {"state": "noupdates", "lastinstall": "2018-01-01T00:00:00"},
            "type": "Dimmable light",
            "name": name,
            "modelid": "LWB010",
            "manufacturername": HUE_MANUFACTURER,
            "productname": "Hue white lamp",
            "capabilities": {
                "certified": True,
                "control": {"mindimlevel": 5000, "maxlumen": 806},
                "streaming": {"renderer": False, "proxy": False},
            },
            "config": {
                "archetype": "classicbulb",
                "function": "mixed",
                "direction": "omnidirectional",
                "startup": {"mode": "safety", "configured": True},
            },
            "uniqueid": "00:17:88:01:00:{:02x}:{:02x}:{:02x}-0b".format(
                (light_id >> 16) & 0xFF,
                (light_id >> 8) & 0xFF,
                light_id & 0xFF,
            ),
            "swversion": "1.50.2_r30933",
        }

    def _build_config_dict(self) -> dict[str, Any]:
        """Build the bridge /config response."""
        return {
            "name": "Home Assistant Bridge",
            "datastoreversion": HUE_DATASTORE_VERSION,
            "swversion": HUE_SW_VERSION,
            "apiversion": HUE_API_VERSION,
            "mac": self.bridge_mac,
            "bridgeid": self.bridge_id,
            "factorynew": False,
            "replacesbridgeid": None,
            "modelid": HUE_MODEL_ID,
            "starterkitid": "",
            "ipaddress": f"{self.host_ip}:{self.advertise_port}",
            "dhcp": True,
            "linkbutton": True,
            "portalservices": False,
            "portalconnection": "disconnected",
            "portalstate": {
                "signedon": False,
                "incoming": False,
                "outgoing": False,
                "communication": "disconnected",
            },
            "internetservices": {"internet": "disconnected", "remoteaccess": "disconnected", "time": "disconnected", "swupdate": "disconnected"},
            "swupdate": {"checkforupdate": False, "devicetypes": {"bridge": False, "lights": [], "sensors": []}, "updatestate": 0, "url": "", "text": "", "notify": False},
            "swupdate2": {"bridge": {"state": "noupdates", "lastinstall": "2018-01-01T00:00:00"}, "checkforupdate": False, "state": "noupdates", "autoinstall": {"on": False, "updatetime": "T14:00:00"}},
            "whitelist": {},
            "zigbeechannel": 25,
            "backup": {"status": "idle", "errorcode": 0},
            "timezone": "UTC",
            "UTC": "2025-01-01T00:00:00",
            "localtime": "2025-01-01T00:00:00",
        }

    @staticmethod
    def _error_response(
        error_type: int, description: str, status: HTTPStatus
    ) -> web.Response:
        """Build a Hue error response."""
        return web.json_response(
            [{"error": {"type": error_type, "address": "/", "description": description}}],
            status=status.value,
        )
