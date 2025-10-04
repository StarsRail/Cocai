import asyncio
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

    def publish(self, event: Dict[str, Any]) -> None:
        # Non-async so it can be called from sync code (e.g., tools)
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop if client is slow; optional: clear and push latest
                pass

    async def close(self) -> None:
        # Signal generators to end and try to flush a shutdown message
        self._closed = True
        try:
            self.publish({"type": "server_shutdown"})
        except Exception:
            pass


broadcaster = Broadcaster()
