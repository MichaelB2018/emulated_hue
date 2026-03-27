"""Persistent per-entity activity tracking for the Emulated Hue integration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.helpers.storage import Store

STORAGE_VERSION = 1
STORAGE_KEY = "emulated_hue_activity"


class ActivityTracker:
    """Track first-discovered and last-controlled timestamps per entity."""

    def __init__(self, store: Store[dict[str, Any]]) -> None:
        """Initialise the tracker with an HA Store instance."""
        self._store = store
        self._data: dict[str, dict[str, str]] = {}
        self._dirty = False

    async def async_load(self) -> None:
        """Load persisted data from disk."""
        stored: dict[str, Any] | None = await self._store.async_load()
        if stored and "entities" in stored:
            self._data = stored["entities"]

    async def async_save(self) -> None:
        """Persist current data to disk if changed."""
        if self._dirty:
            await self._store.async_save({"entities": self._data})
            self._dirty = False

    def record_discovery(self, entity_id: str) -> None:
        """Record that an entity was served in a lights response."""
        entry = self._data.setdefault(entity_id, {})
        if "first_discovered" not in entry:
            entry["first_discovered"] = _now_iso()
            self._dirty = True

    def record_control(self, entity_id: str) -> None:
        """Record that a command was received for an entity."""
        entry = self._data.setdefault(entity_id, {})
        if "first_discovered" not in entry:
            entry["first_discovered"] = _now_iso()
        entry["last_controlled"] = _now_iso()
        self._dirty = True

    def get_entity_activity(self, entity_id: str) -> dict[str, str | None]:
        """Return activity timestamps for an entity."""
        entry = self._data.get(entity_id, {})
        return {
            "first_discovered": entry.get("first_discovered"),
            "last_controlled": entry.get("last_controlled"),
        }

    @property
    def all_activity(self) -> dict[str, dict[str, str]]:
        """Return all tracked data (read-only snapshot)."""
        return dict(self._data)


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
