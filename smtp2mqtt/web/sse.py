import asyncio
import json
import logging
from typing import Any, Dict, Set

log = logging.getLogger("smtp2mqtt.sse")


class SSEBroadcaster:
    """Manages Server-Sent Events (SSE) subscribers and broadcasts real-time event JSON."""

    def __init__(self):
        self._subscribers: Set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        """Subscribes a new HTTP client connection to the SSE stream."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        log.debug("New SSE subscriber added. Total subscribers: %s", len(self._subscribers))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Removes an HTTP client connection queue from the SSE stream."""
        self._subscribers.discard(queue)
        log.debug("SSE subscriber removed. Remaining subscribers: %s", len(self._subscribers))

    def broadcast(self, data: Dict[str, Any], event_type: str = "event") -> None:
        """Broadcasts a payload dict to all connected SSE clients."""
        if not self._subscribers:
            return

        payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        dead_queues = set()

        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                dead_queues.add(queue)

        for dead in dead_queues:
            self._subscribers.discard(dead)
