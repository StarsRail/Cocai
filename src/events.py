import asyncio
import logging
from typing import Any, Dict, List


class Broadcaster:
    """A simple in-memory pub-sub broadcaster for server-sent events (SSE)."""

    def __init__(self, max_queue: int = 100) -> None:
        self._queues: List[asyncio.Queue] = []
        self._max_queue = max_queue
        self._lock = asyncio.Lock()
        self._closed = False

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(self._max_queue)
        async with self._lock:
            self._queues.append(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            if q in self._queues:
                self._queues.remove(q)

    def publish(self, event: Dict[str, Any], context: str = "") -> bool:
        """
        Publish an event to all subscribed listeners with error handling.

        Non-async so it can be called from sync code (e.g., tools).

        Args:
            event: The event dict to publish (e.g., {"type": "clues", "clues": [...]})
            context: Optional context string for error logging (e.g., "record_a_clue")

        Returns:
            True if at least one listener received the event, False on complete failure.
        """
        logger = logging.getLogger("events.Broadcaster")
        try:
            published_count = 0
            for q in list(self._queues):
                try:
                    q.put_nowait(event)
                    published_count += 1
                except asyncio.QueueFull:
                    # Drop if client is slow; optional: clear and push latest
                    pass
            return published_count > 0
        except Exception as e:
            if context:
                logger.error(
                    f"Failed to publish event ({context}): {event}", exc_info=e
                )
            else:
                logger.error("Failed to publish event", exc_info=e)
            return False

    async def close(self) -> None:
        # Signal generators to end and try to flush a shutdown message
        self._closed = True
        try:
            self.publish({"type": "server_shutdown"})
        except Exception:
            pass


broadcaster = Broadcaster()
