import asyncio

import pytest

from async_panes.pane_update_manager import BackgroundPaneUpdateManager


@pytest.mark.asyncio
async def test_latest_generation_wins():
    manager = BackgroundPaneUpdateManager()
    committed: list[str] = []

    async def work(tag):
        # Simulate variable latency
        await asyncio.sleep(0.05 if tag == "old" else 0.01)
        committed.append(tag)

    gen1 = manager.advance_generation()
    manager.schedule("history", gen1, lambda: work("old"))

    # Before the first finishes, schedule a new generation
    gen2 = manager.advance_generation()
    manager.schedule("history", gen2, lambda: work("new"))

    await asyncio.sleep(0.2)
    # Only the latest task's side effect should remain; old task may run but we expect cancellation or staleness
    assert committed[-1] == "new"


@pytest.mark.asyncio
async def test_cancel_all():
    manager = BackgroundPaneUpdateManager()
    started = asyncio.Event()

    async def long_work():
        started.set()
        await asyncio.sleep(1)

    gen = manager.advance_generation()
    manager.schedule("scene", gen, long_work)
    await started.wait()
    manager.cancel_all()
    task = manager.task_for("scene")
    # Task reference removed after cancel_all
    assert task is None or task.cancelled() or task.done()
