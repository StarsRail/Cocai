# async_panes

This module provides utilities for managing asynchronous UI panes in the Cocai  "play" interface (see `public/play.html` for how it looks):

* "story so far" history summary.
* scene illustrations.

Refer to `main.py` for how these coroutines are wired onto the "user sent a message" event.

## Background Pane Update Manager

The chat experience spawns *non-blocking* background tasks after each
user→agent exchange to update auxiliary panes (history text + scene
illustration). These tasks can involve multiple LLM calls and, for the
scene, an optional Stable Diffusion generation. To ensure they never
delay the primary response and never apply stale results, we use a small
`BackgroundPaneUpdateManager` (`src/async_panes/pane_update_manager.py`).

Key behaviors:

* Per pane ("history", "scene") at most one task runs at a time.
* Each incoming user message increments a generation counter; newly
  scheduled tasks capture that generation.
* Scheduling the same pane cancels any prior task immediately.
* If a task starts after being superseded (rare race), its work is
  skipped due to the generation mismatch guard.
* Optional debounce (currently 150ms) and per-task timeout safeguards
  prevent runaway resource usage.

Integration points:

* Initialized per session in `main.factory()` and stored in
  Chainlit's `user_session` under `pane_update_manager`.
* Used in `handle_message_from_user()` to schedule background updates
  instead of raw `asyncio.create_task` calls.
* Cleaned up on `@cl.on_chat_end` via `cancel_all()` to avoid dangling
  tasks when a session ends.

If you add a new auxiliary pane, simply call:

```python
gen = manager.advance_generation()  # already done once per message currently
manager.schedule(
    "my_new_pane", gen, lambda: update_my_new_pane(...), timeout=45.0, debounce=0.15
)
```

Keep pane update coroutines idempotent and resilient to cancellation
(`asyncio.CancelledError` should be re-raised). Avoid performing the
final UI/state mutation until the end of the coroutine so cancellation
prevents partial commits.

## Status Phases (SSE)

History (`type=history_status`): `evaluating`, `summarizing`, `updated`,
`unchanged`, `cancelled`, `error`.

Scene (`type=scene_status`): `evaluating`, `describing`, `imaging`,
`imaging_failed`, `updated`, `unchanged`, `cancelled`, `error`.

Frontend (`public/play.js`) listens and toggles CSS classes:

* `loading-soft`: animated stripe overlay while a phase is in progress.
* `updating-soft`: pulse highlight after successful update.

Styles live in `public/play.css`. We intentionally use *indeterminate*
feedback (no percentage bars) because LLM + diffusion latency is highly
variable; a fake ETA would mislead users.
