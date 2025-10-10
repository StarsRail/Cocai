"""Pane update background task manager.

This centralizes the logic for running *at most one* background update task per
pane (e.g., "history", "scene") for a chat session. Each incoming user message
advances a generation counter; tasks scheduled for older generations become
stale and should not commit results.

Key design points:
- Generation-based staleness guard: a task captures the generation at schedule
  time and checks it at important phase boundaries (your existing update
  helpers are single-phase; we still guard just before/after they run).
- Immediate cancellation of prior task for the same pane when a new one is
  scheduled.
- Central exception logging so failures don't get swallowed silently.
- Optional debounce parameter (can be extended) and timeout wrapper helpers.

We intentionally keep this very small; heavier workflow/actor frameworks would
add complexity without much benefit for this use case.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("pane_update_manager")


@dataclass
class _Scheduled:
    task: asyncio.Task
    generation: int


class BackgroundPaneUpdateManager:
    """Manage cancellable background update tasks per pane.

    Usage pattern per message:
        gen = manager.advance_generation()
        manager.schedule("history", gen, lambda: update_history_if_needed(...))
        manager.schedule("scene", gen, lambda: update_scene_if_needed(...))
    """

    def __init__(self) -> None:
        self._generation: int = 0
        self._tasks: dict[str, _Scheduled] = {}

    @property
    def generation(self) -> int:
        return self._generation

    def advance_generation(self) -> int:
        self._generation += 1
        return self._generation

    def cancel_all(self) -> None:
        for sched in list(self._tasks.values()):  # copy to avoid mutation during loop
            if not sched.task.done():
                sched.task.cancel()
        self._tasks.clear()

    def schedule(
        self,
        pane: str,
        generation: int,
        work_factory: Callable[[], Awaitable[Any]],
        *,
        timeout: float | None = None,
        debounce: float | None = None,
    ) -> None:
        """Schedule work for a pane tied to a specific generation.

        If a previous task for the pane exists, it's cancelled immediately.
        The provided factory is only invoked inside the created task.

        Args:
            pane: Logical pane name ('history', 'scene', etc.).
            generation: Current generation id returned by advance_generation().
            work_factory: Zero-arg callable returning an awaitable (the actual update).
            timeout: Optional overall timeout for the work.
            debounce: Optional initial sleep before starting (if superseded during
                      debounce, the stale task will still run but commit will be skipped
                      due to generation mismatch). For strict debounce that avoids even
                      starting, implement externally before calling schedule().
        """
        # Cancel existing
        if (existing := self._tasks.get(pane)) and not existing.task.done():
            existing.task.cancel()

        async def runner(captured_gen: int):  # noqa: D401
            if debounce:
                try:
                    await asyncio.sleep(debounce)
                except asyncio.CancelledError:
                    raise
            if captured_gen != self._generation:
                # Stale before starting heavy work.
                return
            try:
                if timeout is not None:
                    # Use asyncio.timeout context in 3.11+
                    async with asyncio.timeout(timeout):
                        await work_factory()
                else:
                    await work_factory()
            except asyncio.CancelledError:
                logger.info("Pane '%s' task cancelled (gen=%s)", pane, captured_gen)
                raise
            except Exception:
                logger.exception("Pane '%s' update failed (gen=%s)", pane, captured_gen)
            finally:
                # Remove reference if this task is still the tracked one
                current = self._tasks.get(pane)
                if current and current.task is asyncio.current_task():
                    self._tasks.pop(pane, None)

        task = asyncio.create_task(
            runner(generation), name=f"pane-update:{pane}:g{generation}"
        )
        self._tasks[pane] = _Scheduled(task=task, generation=generation)

    def task_for(self, pane: str) -> asyncio.Task | None:
        sched = self._tasks.get(pane)
        return sched.task if sched else None
