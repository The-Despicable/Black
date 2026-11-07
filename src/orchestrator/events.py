"""Minimal event bus for orchestrator agents."""

import asyncio
import logging
from typing import Any

logger = logging.getLogger("events")


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list] = {}
        self._running = False

    def subscribe(self, event_type: str, callback) -> None:
        self._subscribers.setdefault(event_type, []).append(callback)

    def start(self) -> None:
        """Start the event bus (no-op for compatibility with engage.py)."""
        self._running = True
        logger.info("EventBus started")

    def stop(self) -> None:
        """Stop the event bus (no-op for compatibility with engage.py)."""
        self._running = False
        logger.info("EventBus stopped")

    async def emit(self, event_type: str, **data) -> None:
        for cb in self._subscribers.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(event_type, data)
                else:
                    cb(event_type, data)
            except Exception:
                logger.exception(f"EventBus handler failed for {event_type}")


event_bus = EventBus()
