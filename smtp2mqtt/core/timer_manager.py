import asyncio
import logging
import time
from typing import Callable, Dict, Optional

log = logging.getLogger("smtp2mqtt.timers")


class TimerManager:
    """Thread-safe Timer Manager for Sliding Window auto-reset handling.
    Uses asyncio.Lock and monotonic time to prevent NTP jump corruption."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self._handles: Dict[str, asyncio.TimerHandle] = {}
        self._lock = asyncio.Lock()

    async def schedule_reset(self, topic: str, seconds: float, callback: Callable[[str], None]) -> bool:
        """Schedules or extends an auto-reset timer for a topic. Returns True if extended."""
        async with self._lock:
            already_triggered = topic in self._handles
            if already_triggered:
                self._handles[topic].cancel()

            if seconds > 0:
                self._handles[topic] = self.loop.call_later(seconds, self._on_timer_expire, topic, callback)

            return already_triggered

    def _on_timer_expire(self, topic: str, callback: Callable[[str], None]) -> None:
        """Internal callback fired when a topic timer expires."""
        asyncio.create_task(self._cleanup_and_fire(topic, callback))

    async def _cleanup_and_fire(self, topic: str, callback: Callable[[str], None]) -> None:
        async with self._lock:
            self._handles.pop(topic, None)
        try:
            callback(topic)
        except Exception as err:
            log.error("Error executing reset callback for topic %s: %s", topic, err)

    async def cancel(self, topic: str) -> None:
        """Cancels a running timer for a topic."""
        async with self._lock:
            handle = self._handles.pop(topic, None)
            if handle:
                handle.cancel()

    async def is_triggered(self, topic: str) -> bool:
        """Checks if a topic currently has an active trigger timer running."""
        async with self._lock:
            return topic in self._handles

    async def cancel_all(self) -> None:
        """Cancels all active timers during shutdown."""
        async with self._lock:
            for handle in self._handles.values():
                handle.cancel()
            self._handles.clear()
