"""Tests for the activity tracking store."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.emulated_hue.store import ActivityTracker


class FakeStore:
    """Minimal stand-in for homeassistant.helpers.storage.Store."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = data
        self.saved: dict[str, Any] | None = None

    async def async_load(self) -> dict[str, Any] | None:
        return self._data

    async def async_save(self, data: dict[str, Any]) -> None:
        self.saved = data


async def test_load_empty_store() -> None:
    """Test loading with no prior data."""
    store = FakeStore(None)
    tracker = ActivityTracker(store)
    await tracker.async_load()
    assert tracker.all_activity == {}


async def test_load_existing_data() -> None:
    """Test loading with previously saved data."""
    store = FakeStore(
        {"entities": {"light.test": {"first_discovered": "2026-01-01T00:00:00+00:00"}}}
    )
    tracker = ActivityTracker(store)
    await tracker.async_load()
    activity = tracker.get_entity_activity("light.test")
    assert activity["first_discovered"] == "2026-01-01T00:00:00+00:00"
    assert activity["last_controlled"] is None


async def test_record_discovery_sets_first_discovered() -> None:
    """Test that recording discovery sets first_discovered once."""
    store = FakeStore(None)
    tracker = ActivityTracker(store)
    await tracker.async_load()

    tracker.record_discovery("light.test")
    activity = tracker.get_entity_activity("light.test")
    assert activity["first_discovered"] is not None

    # Second call should not change the timestamp
    first_ts = activity["first_discovered"]
    tracker.record_discovery("light.test")
    assert tracker.get_entity_activity("light.test")["first_discovered"] == first_ts


async def test_record_control_sets_last_controlled() -> None:
    """Test that recording a control command updates last_controlled."""
    store = FakeStore(None)
    tracker = ActivityTracker(store)
    await tracker.async_load()

    tracker.record_control("light.test")
    activity = tracker.get_entity_activity("light.test")
    assert activity["first_discovered"] is not None
    assert activity["last_controlled"] is not None


async def test_save_only_when_dirty() -> None:
    """Test that save is a no-op when nothing changed."""
    store = FakeStore(None)
    tracker = ActivityTracker(store)
    await tracker.async_load()

    await tracker.async_save()
    assert store.saved is None  # Nothing changed, no write

    tracker.record_discovery("light.test")
    await tracker.async_save()
    assert store.saved is not None
    assert "light.test" in store.saved["entities"]


async def test_get_unknown_entity_returns_nones() -> None:
    """Test that querying an unknown entity returns None timestamps."""
    store = FakeStore(None)
    tracker = ActivityTracker(store)
    await tracker.async_load()

    activity = tracker.get_entity_activity("light.unknown")
    assert activity == {"first_discovered": None, "last_controlled": None}
