# Emulated Hue — Home Assistant Custom Integration

A Home Assistant custom integration that exposes selected entities as
Philips Hue lights on the local network.  Alexa (and any other
Hue-compatible client) discovers and controls them without cloud
services or an Alexa skill — everything stays on your LAN.

This is a modernised fork of the
[original `emulated_hue` integration](https://www.home-assistant.io/integrations/emulated_hue)
that ships with Home Assistant Core.  The core version relies on YAML
configuration and has not been updated to current HA standards.
This fork replaces YAML with a full **UI-based config flow** (setup +
options), adds comprehensive tests, and meets the Home Assistant
**Platinum quality scale**.

> **Simpler alternative — no port-80 conflict at all.**
> If the only reason you want Emulated Hue is to let Alexa control HA
> entities, consider
> [**fauxmo**](https://github.com/MichaelB2018/fauxmo) instead.
> Fauxmo emulates Belkin WeMo devices on **port 1900** (UPnP/SSDP),
> which does not conflict with Home Assistant or any other web server
> on port 80.  It achieves exactly the same result — Alexa discovers
> and controls your HA entities locally — without requiring a reverse
> proxy or add-on.

## How it works

```
┌─────────┐  SSDP/UDP 1900   ┌──────────────────────┐
│  Alexa  │ ───────────────►  │  SSDP Responder      │
│  Echo   │  ◄─────────────── │  (upnp.py)           │
│         │  description.xml  │                      │
│         │ ─────────────────►│  Hue REST API        │
│         │  /api, /lights    │  (hue_api.py)        │
│         │  ◄────────────────│                      │
└─────────┘   JSON responses  └──────────┬───────────┘
                                         │
                              calls HA services
                              (turn_on / turn_off)
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │   Home Assistant      │
                              │   entity states       │
                              └──────────────────────┘
```

1. **SSDP discovery** — A UDP responder on port 1900 answers Alexa's
   M-SEARCH broadcasts and sends periodic NOTIFY advertisements.
2. **Hue bridge REST API** — An aiohttp HTTP server implements the
   subset of the Philips Hue API that Alexa uses: registration
   (`POST /api`), lights listing (`GET /api/{user}/lights`),
   individual light state (`GET/PUT .../lights/{id}/state`), and the
   bridge description XML.
3. **Entity mapping** — Each selected HA entity gets a stable Hue
   light ID.  On/off commands are translated to `homeassistant.turn_on`
   / `homeassistant.turn_off` service calls (scenes use `scene.turn_on`).

## Supported entity domains

`input_boolean`, `light`, `scene`, `script`, `switch`

## Installation

Copy `custom_components/emulated_hue/` into your Home Assistant
`config/custom_components/` directory.  Restart Home Assistant.

### Port 80 — understanding the requirement

Alexa expects any Philips Hue bridge to respond on **port 80**.
How you satisfy that requirement depends on whether something else on
your HA host is already using port 80:

| Scenario | What to do |
|----------|------------|
| **Port 80 is free** (HA runs on 8123, no other web server on 80) | Set both *Listen port* **and** *Advertise port* to **80** in the integration options.  Emulated Hue binds directly to port 80 — no add-on needed. |
| **Port 80 is already in use** (e.g. HA itself, another reverse proxy, or another service occupies port 80) | Use the bundled **NGINX Hue Proxy** add-on (see below).  The add-on captures port 80 and forwards Hue-specific paths to Emulated Hue while sending everything else to the existing service. |

In other words, the **NGINX add-on is entirely optional**.  You only
need it when port 80 is already claimed by another process on the same
host.

### NGINX Hue Proxy add-on (only when port 80 is shared)

When port 80 is occupied by another service, the bundled NGINX add-on
multiplexes port 80:

- Hue-specific paths (`/description.xml`, `/api`, `/api/{username}/…`)
  route to the emulated Hue server (default port 8300).
- Everything else routes to Home Assistant (port 8123).

Install the add-on from `nginx-hue-proxy/` as a local add-on:

1. Copy the `nginx-hue-proxy/` folder to `/addons/nginx-hue-proxy/`
   on your HA host.
2. Go to **Settings → Add-ons → Add-on Store → ⋮ → Check for updates**.
3. Install and start the **NGINX Hue Proxy** add-on.
4. Set the integration's **Advertise port** to `80` so SSDP broadcasts
   point Alexa to port 80 (where NGINX is listening).

## Configuration

After installation, add the integration via the UI:

**Settings → Devices & Services → Add Integration → Emulated Hue**

| Option         | Default | Description |
|----------------|---------|-------------|
| Listen port    | 8300    | TCP port for the Hue API server. |
| Advertise port | 80      | Port advertised in SSDP responses.  Set to 80 when using the NGINX proxy. |

### Selecting entities

Open the integration's **Options** to pick which entities to expose
and set custom Alexa-visible names:

1. Select entities from the supported domains.
2. Set a custom name for each (or leave blank to use the
   entity's friendly name).
3. Save.  Changes apply immediately — no restart required.

## Architecture

```
custom_components/emulated_hue/
├── __init__.py        # Integration lifecycle: setup, unload, options update
├── config_flow.py     # Config flow UI (setup + options)
├── const.py           # Constants (ports, domain, Hue API versions)
├── diagnostics.py     # Diagnostic data export
├── hue_api.py         # Hue bridge REST API (aiohttp)
├── manifest.json      # HA integration manifest
├── quality_scale.yaml # HA quality scale checklist
├── store.py           # Persistent per-entity activity tracking
├── strings.json       # Localisation source strings
├── translations/
│   └── en.json        # English translations
└── upnp.py            # SSDP/UPnP discovery responder

nginx-hue-proxy/       # HA add-on: NGINX reverse proxy
├── build.yaml
├── config.yaml
├── Dockerfile
├── nginx.conf
└── run.sh

tests/components/emulated_hue/
├── conftest.py         # Shared fixtures
├── test_config_flow.py
├── test_hue_api.py
├── test_init.py
├── test_store.py
└── test_upnp.py
```

### Key design decisions

- **Deterministic bridge identity** — The bridge ID, MAC address, and
  Hue username are derived from the HA host IP so they remain stable
  across restarts without persisted state.
- **No polling** — State is read from HA at request time; SSDP uses
  UDP multicast.  Classification: `local_push`.
- **Activity tracking** — `store.py` records per-entity
  `first_discovered` and `last_controlled` timestamps, viewable in
  the diagnostics panel.
- **Auto-reload on port change** — Changing port settings in the
  options flow triggers a full integration reload so the HTTP server
  and SSDP responder bind to the new ports.

## Alexa discovery checklist

If Alexa doesn't find your devices, verify:

1. **Port 80 reachable** — `curl http://<HA_IP>/description.xml`
   should return XML with `Philips hue bridge 2015`.
2. **API responds** — `curl http://<HA_IP>/api/<username>/lights`
   should return your entities as JSON.
3. **SSDP working** — Check HA logs (set `emulated_hue` to debug
   level) for M-SEARCH / NOTIFY activity.
4. **Same subnet** — Alexa and HA must be on the same LAN subnet
   (SSDP multicast doesn't cross routers).
5. **No duplicate Hue bridges** — If a real Hue bridge is on the
   network, Alexa may bind to it instead.

## Development

### Running tests

```sh
pytest tests/components/emulated_hue/ -v
```

### Logging

Production logging is minimal.  To enable verbose diagnostics:

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.emulated_hue: debug
```

This surfaces per-request HTTP handling, SSDP M-SEARCH/NOTIFY details,
and response payloads.

## Repository

<https://github.com/MichaelB2018/emulated_hue>

## License

This project is provided under the same license as Home Assistant Core.
