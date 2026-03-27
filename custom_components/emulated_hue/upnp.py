"""SSDP/UPnP discovery responder for the Emulated Hue integration.

Broadcasts the emulated Hue bridge on the local network so that Alexa
and other Hue clients can discover it automatically via SSDP (UDP 1900).
"""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any

from homeassistant.core import HomeAssistant

from .const import SSDP_MAX_AGE, SSDP_MULTICAST_ADDR, SSDP_NOTIFY_INTERVAL, SSDP_PORT

_LOGGER = logging.getLogger(__name__)


class UPnPResponder(asyncio.DatagramProtocol):
    """SSDP/UPnP protocol that responds to M-SEARCH requests.

    Also sends periodic NOTIFY advertisements so clients can discover
    the bridge without active searching.
    """

    def __init__(
        self,
        host_ip: str,
        listen_port: int,
        bridge_mac: str,
        advertise_port: int | None = None,
        bridge_id: str | None = None,
    ) -> None:
        """Initialise the UPnP responder."""
        self.host_ip = host_ip
        self.listen_port = listen_port
        self.advertise_port = advertise_port or listen_port
        self.bridge_mac = bridge_mac
        self.bridge_id = bridge_id or bridge_mac.replace(':', '').upper()
        self._transport: asyncio.DatagramTransport | None = None
        self._notify_task: asyncio.Task[None] | None = None
        self._usn = f"uuid:2f402f80-da50-11e1-9b23-{bridge_mac.replace(':', '')}::upnp:rootdevice"

    @property
    def _location(self) -> str:
        """Return the URL to the bridge description.xml."""
        return f"http://{self.host_ip}:{self.advertise_port}/description.xml"

    # ------------------------------------------------------------------
    # Protocol callbacks
    # ------------------------------------------------------------------

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Handle connection established."""
        self._transport = transport  # type: ignore[assignment]
        _LOGGER.debug("SSDP responder listening on %s:%s", SSDP_MULTICAST_ADDR, SSDP_PORT)
        loop = asyncio.get_running_loop()
        self._notify_task = loop.create_task(self._notify_loop())

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle connection lost."""
        if self._notify_task is not None:
            self._notify_task.cancel()
            self._notify_task = None
        _LOGGER.debug("SSDP responder stopped")

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle incoming SSDP M-SEARCH requests."""
        try:
            message = data.decode("utf-8", errors="replace")
        except Exception:
            return

        if "M-SEARCH" not in message:
            return

        # Determine which search target was requested — parse the ST
        # header properly and compare case-insensitively.
        message_lower = message.lower()
        requested_st: str | None = None
        for target in (
            "ssdp:all",
            "upnp:rootdevice",
            "urn:schemas-upnp-org:device:basic:1",
        ):
            if target in message_lower:
                requested_st = target
                break

        if requested_st is None:
            # Extract the actual ST line for diagnostics
            st_line = "unknown"
            for line in message.splitlines():
                if line.strip().upper().startswith("ST:"):
                    st_line = line.strip()
                    break
            _LOGGER.debug("SSDP ignoring M-SEARCH from %s:%s (unrecognised %s)", addr[0], addr[1], st_line)
            return

        _LOGGER.debug("SSDP M-SEARCH from %s:%s (ST: %s)", addr[0], addr[1], requested_st)
        response = self._build_search_response(requested_st)
        if self._transport is not None:
            self._transport.sendto(response.encode("utf-8"), addr)
            _LOGGER.debug("SSDP response sent to %s:\n%s", addr, response.rstrip())

    # ------------------------------------------------------------------
    # SSDP message builders
    # ------------------------------------------------------------------

    def _build_search_response(self, search_target: str = "upnp:rootdevice") -> str:
        """Build the SSDP M-SEARCH response."""
        # For ssdp:all, respond as upnp:rootdevice (the canonical Hue type)
        st = "upnp:rootdevice" if search_target == "ssdp:all" else search_target
        return (
            "HTTP/1.1 200 OK\r\n"
            f"CACHE-CONTROL: max-age={SSDP_MAX_AGE}\r\n"
            "EXT:\r\n"
            f"LOCATION: {self._location}\r\n"
            'SERVER: Linux/3.14.0 UPnP/1.0 IpBridge/1.56.0\r\n'
            f"hue-bridgeid: {self.bridge_id}\r\n"
            f"ST: {st}\r\n"
            f"USN: {self._usn}\r\n"
            "\r\n"
        )

    def _build_notify(self) -> str:
        """Build a SSDP NOTIFY advertisement."""
        return (
            "NOTIFY * HTTP/1.1\r\n"
            f"HOST: {SSDP_MULTICAST_ADDR}:{SSDP_PORT}\r\n"
            f"CACHE-CONTROL: max-age={SSDP_MAX_AGE}\r\n"
            f"LOCATION: {self._location}\r\n"
            'SERVER: Linux/3.14.0 UPnP/1.0 IpBridge/1.56.0\r\n'
            f"hue-bridgeid: {self.bridge_id}\r\n"
            "NTS: ssdp:alive\r\n"
            f"NT: upnp:rootdevice\r\n"
            f"USN: {self._usn}\r\n"
            "\r\n"
        )

    # ------------------------------------------------------------------
    # Periodic NOTIFY broadcast
    # ------------------------------------------------------------------

    async def _notify_loop(self) -> None:
        """Periodically send SSDP NOTIFY advertisements."""
        try:
            while True:
                if self._transport is not None:
                    msg = self._build_notify().encode("utf-8")
                    self._transport.sendto(
                        msg, (SSDP_MULTICAST_ADDR, SSDP_PORT)
                    )
                    _LOGGER.debug("SSDP NOTIFY broadcast (LOCATION: %s)", self._location)
                await asyncio.sleep(SSDP_NOTIFY_INTERVAL)
        except asyncio.CancelledError:
            pass


async def create_upnp_responder(
    hass: HomeAssistant,
    host_ip: str,
    listen_port: int,
    bridge_mac: str,
    advertise_port: int | None = None,
    bridge_id: str | None = None,
) -> tuple[asyncio.DatagramTransport, UPnPResponder]:
    """Create and start the SSDP/UPnP responder.

    Returns the transport and protocol so the caller can close them
    during integration unload.
    """
    loop = asyncio.get_running_loop()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass

    sock.bind(("", SSDP_PORT))

    group = socket.inet_aton(SSDP_MULTICAST_ADDR)
    mreq = group + socket.inet_aton(host_ip)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    sock.setsockopt(
        socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(host_ip)
    )

    sock.setblocking(False)

    transport, protocol = await loop.create_datagram_endpoint(
        lambda: UPnPResponder(host_ip, listen_port, bridge_mac, advertise_port, bridge_id),
        sock=sock,
    )

    _LOGGER.info(
        "SSDP responder started on %s for bridge at %s:%s (advertise_port=%s, LOCATION=%s)",
        SSDP_MULTICAST_ADDR,
        host_ip,
        listen_port,
        advertise_port or listen_port,
        f"http://{host_ip}:{advertise_port or listen_port}/description.xml",
    )

    return transport, protocol  # type: ignore[return-value]
