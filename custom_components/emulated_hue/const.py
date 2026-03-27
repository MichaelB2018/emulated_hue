"""Constants for the Emulated Hue integration."""

from typing import Final

DOMAIN: Final = "emulated_hue"

DEFAULT_LISTEN_PORT: Final = 8300
DEFAULT_BRIDGE_NAME: Final = "Home Assistant Bridge"

# Config entry keys
CONF_LISTEN_PORT: Final = "listen_port"
CONF_ADVERTISE_PORT: Final = "advertise_port"
CONF_ENTITIES: Final = "entities"
CONF_ENTITY_NAME: Final = "name"

# Hue API constants
HUE_API_VERSION: Final = "1.56.0"
HUE_DATASTORE_VERSION: Final = "152"
HUE_SW_VERSION: Final = "1956006050"
HUE_MODEL_ID: Final = "BSB002"
HUE_MANUFACTURER: Final = "Royal Philips Electronics"

# SSDP constants
SSDP_MULTICAST_ADDR: Final = "239.255.255.250"
SSDP_PORT: Final = 1900
SSDP_MAX_AGE: Final = 1800
SSDP_NOTIFY_INTERVAL: Final = 60

# Entity domain filter for the entity picker
SUPPORTED_DOMAINS: Final = frozenset(
    {"input_boolean", "scene", "switch", "light", "script"}
)
