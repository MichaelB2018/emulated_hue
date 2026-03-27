"""The Emulated Hue integration.

Exposes Home Assistant entities as Philips Hue lights on the local
network, allowing Alexa and other Hue-compatible clients to discover
and control them via the Hue bridge API.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import web

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.network import get_url
from homeassistant.helpers.storage import Store

from .const import (
    CONF_ADVERTISE_PORT,
    CONF_ENTITIES,
    CONF_LISTEN_PORT,
    DEFAULT_LISTEN_PORT,
    DOMAIN,
)
from .hue_api import HueAPI
from .store import STORAGE_KEY, STORAGE_VERSION, ActivityTracker
from .upnp import create_upnp_responder

_LOGGER = logging.getLogger(__name__)

type EmulatedHueConfigEntry = ConfigEntry


# ------------------------------------------------------------------
# Config-entry lifecycle
# ------------------------------------------------------------------

def _derive_bridge_identifiers(
    host_ip: str,
) -> tuple[str, str]:
    """Derive a stable bridge ID and MAC from the host IP address.

    Returns (bridge_id, bridge_mac) where bridge_id is a 16-char hex
    string and bridge_mac is colon-separated.
    """
    octets = host_ip.split(".")
    mac_parts = [
        "00",
        "17",
        "88",
        f"{int(octets[1]):02x}",
        f"{int(octets[2]):02x}",
        f"{int(octets[3]):02x}",
    ]
    bridge_mac = ":".join(mac_parts)
    bridge_id = "".join(mac_parts).upper() + "FFFE" + mac_parts[-1].upper()
    bridge_id = bridge_id[:16]
    return bridge_id, bridge_mac


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EmulatedHueConfigEntry,
) -> bool:
    """Set up Emulated Hue from a config entry."""
    listen_port: int = entry.data.get(CONF_LISTEN_PORT, DEFAULT_LISTEN_PORT)
    advertise_port: int = entry.data.get(CONF_ADVERTISE_PORT, listen_port)
    entities: dict[str, dict[str, str]] = entry.options.get(CONF_ENTITIES, {})

    host_ip = _get_host_ip(hass)
    bridge_id, bridge_mac = _derive_bridge_identifiers(host_ip)

    # Activity tracking (persistent per-entity timestamps)
    tracker = ActivityTracker(
        Store(hass, STORAGE_VERSION, STORAGE_KEY)
    )
    await tracker.async_load()

    _LOGGER.info(
        "Starting Emulated Hue on %s:%s (advertise_port=%s, bridge %s, mac %s, %d entities)",
        host_ip,
        listen_port,
        advertise_port,
        bridge_id,
        bridge_mac,
        len(entities),
    )

    hue_api = HueAPI(
        hass=hass,
        bridge_id=bridge_id,
        bridge_mac=bridge_mac,
        host_ip=host_ip,
        listen_port=listen_port,
        advertise_port=advertise_port,
        activity_tracker=tracker,
    )
    hue_api.update_entities(entities)

    app = hue_api.create_app()
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", listen_port)
    try:
        await site.start()
    except OSError as err:
        _LOGGER.error(
            "Failed to start Hue API server on port %s: %s", listen_port, err
        )
        await runner.cleanup()
        return False

    _LOGGER.info("Hue API server listening on port %s", listen_port)

    # Start SSDP responder
    ssdp_transport: asyncio.DatagramTransport | None = None
    try:
        ssdp_transport, _protocol = await create_upnp_responder(
            hass, host_ip, listen_port, bridge_mac, advertise_port, bridge_id
        )
    except OSError as err:
        _LOGGER.warning(
            "Failed to start SSDP responder (Alexa discovery may not work): %s",
            err,
        )

    # Store references for cleanup and options updates
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "hue_api": hue_api,
        "runner": runner,
        "site": site,
        "ssdp_transport": ssdp_transport,
        "activity_tracker": tracker,
        "listen_port": listen_port,
        "advertise_port": advertise_port,
    }

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    async def _async_on_stop(event: Event) -> None:
        await _async_cleanup(hass, entry)

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_on_stop)
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: EmulatedHueConfigEntry,
) -> bool:
    """Unload an Emulated Hue config entry."""
    await _async_cleanup(hass, entry)
    return True


async def _async_cleanup(
    hass: HomeAssistant,
    entry: EmulatedHueConfigEntry,
) -> None:
    """Stop the Hue API server and SSDP responder."""
    data: dict[str, Any] | None = hass.data.get(DOMAIN, {}).pop(
        entry.entry_id, None
    )
    if data is None:
        return

    runner: web.AppRunner = data["runner"]
    ssdp_transport: asyncio.DatagramTransport | None = data.get("ssdp_transport")
    tracker: ActivityTracker | None = data.get("activity_tracker")

    if tracker is not None:
        await tracker.async_save()

    if ssdp_transport is not None:
        ssdp_transport.close()

    await runner.cleanup()
    _LOGGER.info("Emulated Hue stopped")


async def _async_options_updated(
    hass: HomeAssistant,
    entry: EmulatedHueConfigEntry,
) -> None:
    """Handle options update — refresh entities or full reload if ports changed."""
    data: dict[str, Any] | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if data is None:
        return

    # If listen_port or advertise_port changed, a full reload is needed
    # because the HTTP server and SSDP responder must be recreated.
    old_listen = data.get("listen_port")
    old_advertise = data.get("advertise_port")
    new_listen = entry.data.get(CONF_LISTEN_PORT, DEFAULT_LISTEN_PORT)
    new_advertise = entry.data.get(CONF_ADVERTISE_PORT, new_listen)

    if old_listen != new_listen or old_advertise != new_advertise:
        _LOGGER.info(
            "Port configuration changed — reloading Emulated Hue"
        )
        await hass.config_entries.async_reload(entry.entry_id)
        return

    hue_api: HueAPI = data["hue_api"]
    entities: dict[str, dict[str, str]] = entry.options.get(CONF_ENTITIES, {})
    hue_api.update_entities(entities)
    _LOGGER.info(
        "Emulated Hue entity mapping updated (%d entities)", len(entities)
    )


def _get_host_ip(hass: HomeAssistant) -> str:
    """Determine the host IP address to use for the bridge."""
    try:
        url = get_url(hass, allow_external=False, prefer_external=False)
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname
        if host and host not in ("localhost", "127.0.0.1", "::1"):
            return host
    except Exception:
        pass

    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
