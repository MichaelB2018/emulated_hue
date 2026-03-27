"""Diagnostics support for the Emulated Hue integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENTITIES, CONF_ENTITY_NAME, CONF_LISTEN_PORT, DOMAIN
from .store import ActivityTracker


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostic data for a config entry."""
    entities: dict[str, dict[str, str]] = entry.options.get(CONF_ENTITIES, {})
    listen_port: int = entry.data.get(CONF_LISTEN_PORT, 0)

    runtime_data: dict[str, Any] = hass.data.get(DOMAIN, {}).get(
        entry.entry_id, {}
    )
    server_running = "runner" in runtime_data
    ssdp_running = runtime_data.get("ssdp_transport") is not None
    tracker: ActivityTracker | None = runtime_data.get("activity_tracker")

    entity_info: list[dict[str, Any]] = []
    for entity_id, entity_conf in entities.items():
        state_obj = hass.states.get(entity_id)
        activity = (
            tracker.get_entity_activity(entity_id) if tracker else {}
        )
        entity_info.append(
            {
                "entity_id": entity_id,
                "custom_name": entity_conf.get(CONF_ENTITY_NAME, ""),
                "state": state_obj.state if state_obj else "unavailable",
                "domain": entity_id.split(".")[0],
                "first_discovered": activity.get("first_discovered"),
                "last_controlled": activity.get("last_controlled"),
            }
        )

    return {
        "listen_port": listen_port,
        "entity_count": len(entities),
        "entities": entity_info,
        "server_running": server_running,
        "ssdp_running": ssdp_running,
    }
