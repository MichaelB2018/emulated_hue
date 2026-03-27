"""Tests for the SSDP/UPnP responder."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.emulated_hue.upnp import UPnPResponder

from .conftest import MOCK_BRIDGE_MAC, MOCK_HOST_IP


def _create_responder() -> UPnPResponder:
    """Create a test UPnP responder."""
    return UPnPResponder(
        host_ip=MOCK_HOST_IP,
        listen_port=8300,
        bridge_mac=MOCK_BRIDGE_MAC,
    )


def test_search_response_format() -> None:
    """Test that the M-SEARCH response is correctly formatted."""
    responder = _create_responder()
    response = responder._build_search_response()

    assert "HTTP/1.1 200 OK" in response
    assert "LOCATION:" in response
    assert f"http://{MOCK_HOST_IP}:8300/description.xml" in response
    assert "ST: upnp:rootdevice" in response
    assert "CACHE-CONTROL:" in response
    assert "USN:" in response
    assert response.endswith("\r\n\r\n")


def test_notify_format() -> None:
    """Test that the NOTIFY advertisement is correctly formatted."""
    responder = _create_responder()
    notify = responder._build_notify()

    assert "NOTIFY * HTTP/1.1" in notify
    assert "NTS: ssdp:alive" in notify
    assert "NT: upnp:rootdevice" in notify
    assert f"http://{MOCK_HOST_IP}:8300/description.xml" in notify
    assert notify.endswith("\r\n\r\n")


def test_bridge_id_in_response() -> None:
    """Test that the bridge ID appears in SSDP responses."""
    responder = _create_responder()
    response = responder._build_search_response()
    # MAC without colons, uppercased
    expected_id = MOCK_BRIDGE_MAC.replace(":", "").upper()
    assert expected_id in response


def test_datagram_received_ignores_non_msearch() -> None:
    """Test that non-M-SEARCH messages are ignored."""
    responder = _create_responder()
    mock_transport = MagicMock()
    responder._transport = mock_transport

    # Send a NOTIFY message (not M-SEARCH)
    responder.datagram_received(
        b"NOTIFY * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n\r\n",
        ("198.51.100.10", 1234),
    )
    # Should not send any response
    mock_transport.sendto.assert_not_called()


def test_datagram_received_responds_to_msearch() -> None:
    """Test that M-SEARCH for our device type gets a response."""
    responder = _create_responder()
    mock_transport = MagicMock()
    responder._transport = mock_transport

    msearch = (
        b"M-SEARCH * HTTP/1.1\r\n"
        b"HOST: 239.255.255.250:1900\r\n"
        b"MAN: \"ssdp:discover\"\r\n"
        b"ST: urn:schemas-upnp-org:device:basic:1\r\n"
        b"MX: 3\r\n"
        b"\r\n"
    )
    responder.datagram_received(msearch, ("198.51.100.10", 1234))
    mock_transport.sendto.assert_called_once()

    sent_data = mock_transport.sendto.call_args[0][0]
    assert b"HTTP/1.1 200 OK" in sent_data
    assert b"description.xml" in sent_data


def test_datagram_received_responds_to_ssdp_all() -> None:
    """Test that M-SEARCH for ssdp:all gets a response."""
    responder = _create_responder()
    mock_transport = MagicMock()
    responder._transport = mock_transport

    msearch = (
        b"M-SEARCH * HTTP/1.1\r\n"
        b"HOST: 239.255.255.250:1900\r\n"
        b"ST: ssdp:all\r\n"
        b"\r\n"
    )
    responder.datagram_received(msearch, ("198.51.100.10", 1234))
    mock_transport.sendto.assert_called_once()


def test_datagram_received_ignores_unrelated_search() -> None:
    """Test that M-SEARCH for unrelated types is ignored."""
    responder = _create_responder()
    mock_transport = MagicMock()
    responder._transport = mock_transport

    msearch = (
        b"M-SEARCH * HTTP/1.1\r\n"
        b"HOST: 239.255.255.250:1900\r\n"
        b"ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n"
        b"\r\n"
    )
    responder.datagram_received(msearch, ("198.51.100.10", 1234))
    mock_transport.sendto.assert_not_called()


def test_location_property() -> None:
    """Test the location URL is correctly formed."""
    responder = _create_responder()
    assert responder._location == f"http://{MOCK_HOST_IP}:8300/description.xml"
