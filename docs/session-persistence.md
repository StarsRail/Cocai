# Session Persistence Architecture

## Overview

This document describes the session persistence system for CoCai, which automatically saves and restores game state across browser refreshes and server restarts. Users no longer lose their conversation history, character data, clues, scene illustrations, or story progression when refreshing the `/play` UI.

## Problem Statement

**Before:** Every page refresh in `/play` created a new session, losing:
- Chat conversation history (visible to agent but not persisted to UI)
- Character data (PC stats, skills, name)
- Discovered clues (left pane accordion)
- Scene illustrations (center pane)
- Story summary / history (left pane)

**After:** All game state survives page refreshes and server restarts, providing a seamless user experience.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ User refreshes /play                                            │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │ play.html loads       │
         │ play.js opens SSE     │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────────────────────┐
         │ /chat iframe loads Chainlit           │
         │ Chainlit checks for existing thread   │
         └───────────┬───────────────────────────┘
                     │
         ┌───────────┴──────────────────────────┐
         │                                      │
         ▼ (existing thread)          ▼ (new session)
    @cl.on_chat_resume          @cl.on_chat_start
         │                            │
         ├─→ Load game state    ├─→ Load game state
         ├─→ Restore agent      ├─→ Create fresh agent
         ├─→ Restore memory     ├─→ Create memory
         │                      └─→ Set up tools
         │
         └──────────┬──────────────────┘
                    │
         ┌──────────▼──────────────────┐
         │ broadcaster.publish() sends │
         │ initial state events        │
         └──────────┬──────────────────┘
                    │
         ┌──────────▼──────────────────┐
         │ SSE stream delivers events  │
         │ + Chainlit persisted        │
         │   messages to UI            │
         └──────────┬──────────────────┘
                    │
         ┌──────────▼──────────────────┐
         │ UI renders:                 │
         │ - Chat history (Chainlit)   │
         │ - Game state (SSE)          │
         └─────────────────────────────┘
```

## Component Architecture

### 1. **Storage Layer** (`game_state/load_and_save.py`)

Provides abstract persistence operations independent of storage backend.

```python
async def save_game_state(game_state: GameState) -> bool
async def load_game_state() -> Optional[GameState]
```

**Storage Backend:** Chainlit's SQLite data layer
- **Table:** `threads` (JSONB column: `metadata`)
- **Key:** `metadata["game_state"]`
- **Format:** Serialized JSON dictionary from `GameState.to_dict()`

**Error Handling:**
- Missing thread ID → logs warning, returns None/False
- No data layer → logs warning, returns None/False
- Malformed metadata → caught, logged, returns None

### 2. **Game State Model** (`game_state/data_models.py`)

```python
@dataclass
class GameState:
    phase: GamePhase
    history: str
    clues: list[Clue]
    illustration_url: str | None
    pc: Character | None

    def to_dict(self) -> dict
    @staticmethod
    def from_dict(data: dict) -> GameState
```

**Serialization Notes:**
- `phase` stored as string (enum value)
- `clues` stored as list of dictionaries
- `pc` (Character object) cannot be fully serialized (cochar limitation)
  - UI representation (stats, skills, name) is preserved
  - Character object reconstructed in memory only when accessed
- All primitive fields included for full data recovery

### 3. **Session Initialization** (`src/main.py` → `@cl.on_chat_start`)

**Flow:**
1. Load any persisted state via `load_game_state()`
2. If None, create fresh `GameState()`
3. Set game state in agent context
4. **Immediately broadcast** all state events to SSE stream
5. Store data_layer in user_session for future persistence calls

**Initial Broadcast (lines ~200-205):**
```python
game_state_dict = user_visible_game_state.to_dict()
broadcaster.publish({"type": "history", "history": ...})
broadcaster.publish({"type": "clues", "clues": ...})
broadcaster.publish({"type": "illustration", "url": ...})
broadcaster.publish({"type": "pc", "pc": ...})
```

This ensures SSE clients connecting after session start receive the full current state.

### 3b. **Conversation Resumption** (`src/main.py` → `@cl.on_chat_resume`)

When a user visits `/play` after a previous session, Chainlit automatically calls `@cl.on_chat_resume` with the previous thread. This hook:

1. Reconstructs the FunctionAgent with the same LLM/memory setup
2. Loads the persisted `GameState` from thread metadata
3. Restores the agent context
4. Broadcasts all state to SSE (so linked panes update)
5. Chainlit automatically restores all chat messages

**Result:** User refreshes page → sees full conversation history + all game state intact

### 4. **Persistence Hooks** (Event Triggers)

Whenever game state mutates, the tool/helper calls `await save_game_state()`:

| File | Trigger | When |
|------|---------|------|
| `agentic_tools/create_character.py` | Character creation | PC created |
| `agentic_tools/misc.py` → `record_a_clue()` | User discovers clue | Clue added/updated |
| `async_panes/history.py` → `update_history_if_needed()` | LLM summarizes story | History text changed |
| `async_panes/scene.py` → `update_scene_if_needed()` | Scene image generated | Illustration URL changed |
| `agentic_tools/illustrate_scene.py` → `set_illustration_url()` | Manual URL set | Illustration URL changed |

## Data Flow Diagram

### Write Path (Persistence):
```
Tool/Helper modifies context state
    ↓
async with ctx.store.edit_state() as ctx_state:
    user_visible_state.property = new_value
    ↓
await save_game_state(user_visible_state)
    ↓
thread.metadata["game_state"] = state_dict
    ↓
SQLite: UPDATE threads SET metadata = ... WHERE id = thread_id
    ↓
broadcaster.publish({"type": "...", ...})
    ↓
SSE stream → UI
```

### Read Path (Restoration):
```
@cl.on_chat_start
    ↓
load_game_state()
    ↓
data_layer.get_thread(thread_id)
    ↓
state_dict = thread.metadata["game_state"]
    ↓
GameState.from_dict(state_dict)
    ↓
agent context receives restored state
    ↓
broadcaster publishes initial events
    ↓
SSE clients receive and render
```

## UI Integration

### SSE Client (`public/play.js`)

Play.js opens an SSE stream to `/api/events`:
```javascript
const es = new EventSource('/api/events')
es.onmessage = (ev) => {
    const msg = JSON.parse(ev.data)
    if (msg.type === 'history') renderHistory(msg.history)
    if (msg.type === 'clues') renderClues(msg.clues)
    if (msg.type === 'illustration') renderIllustration(msg.url)
    if (msg.type === 'pc') renderPC(msg.pc)
}
```

**On Reconnect:** Play.js closes and reopens the EventSource connection. At that moment:
1. `/api/events` handler calls `broadcaster.subscribe()`
2. New queue receives the next messages from broadcaster
3. If Chainlit has already broadcasted initial state, the event is lost (queues only store pending events)
4. Solution: Chainlit broadcasts initial state in `@cl.on_chat_start` to ensure new clients receive it

**Key Assumption:** The Chainlit session (`/chat` iframe) starts before the UI fully connects to SSE, so the initial broadcast has time to propagate.

## State Persistence Strategy

### When is state saved?

**Eager persistence (synchronous write on every mutation):**
- Saves are called after every user-visible state change
- Ensures durability if server crashes
- Trade-off: Small latency overhead (~5-50ms per save)

### What is NOT persisted?

- **Chainlit message history:** Already persisted by Chainlit's data layer
- **Agent memory (Mem0):** Mem0 has its own persistence to Qdrant
- **Raw Character object:** Cannot serialize cochar.Character objects reliably
  - Only the UI representation (stats dict) is preserved
  - Character must be recreated via agent if needed for computation

### Concurrent Access

- **Per-thread:** Each user/session has isolated `thread_id`, so no conflicts
- **Thread safety:** Chainlit handles concurrent writes to threads table
- **Metadata atomicity:** SQLite handles metadata JSONB updates atomically

## Extension Points

### Adding New Persistent Fields

To persist a new property (e.g., `player_notes: str`):

1. Add field to `GameState` dataclass
2. Update `to_dict()` to include the field
3. Update `from_dict()` to deserialize it
4. Call `save_game_state()` after mutations
5. Add SSE broadcast in `@cl.on_chat_start` if needed for UI

### Using Different Storage Backend

Currently uses Chainlit's SQLAlchemy data layer. To switch backends:

1. Replace `save_game_state()` and `load_game_state()` in `load_and_save.py`
2. Backends to consider:
   - PostgreSQL (via SQLAlchemy)
   - Redis (fast, in-memory)
   - Firebase Firestore (cloud)
   - Custom API

### Manual State Adjustments

If you need to manually inspect/edit persisted state:

```python
# Connect to Chainlit's data layer
from utils import set_up_data_layer
data_layer = set_up_data_layer()

# Query a thread's game state
thread = await data_layer.get_thread(thread_id)
game_state = thread.metadata.get("game_state")

# Modify and update
game_state["history"] = "New history..."
thread.metadata["game_state"] = game_state
await data_layer.update_thread(thread_id, thread.metadata)
```

## Testing Checklist

To verify session persistence works:

- [ ] Create character → refresh page → character restored
- [ ] Add clues → refresh → clues visible in left accordion
- [ ] Generate scene image → refresh → illustration appears
- [ ] Chat several turns → refresh → story summary in history pane
- [ ] Server restart → session reconnects with full state
- [ ] Multiple browser tabs → each maintains independent state (separate threads)
- [ ] Create character, leave tab for 1 hour → return and refresh → state still there

## Performance Implications

### Latency
- Per-save overhead: ~5–50ms (SQLite write + broadcaster publish)
- Impact: Minimal, async and non-blocking
- Broadcaster publish: ~1ms (in-memory queue)

### Storage
- Per-GameState: ~500B–5KB depending on clue count and illustration URL length
- Over time: Threads table grows, but each thread's metadata is small
- Recommendation: Periodically archive old threads or implement TTL

### Concurrency
- Each session has its own thread → no lock contention
- Broadcaster uses asyncio.Lock for thread safety
- SQLite single-writer model handles updates sequentially

## Debugging & Logging

**Key Log Lines:**

```
# Session initialization
"Loaded persisted game state." or "No persisted game state found; creating a new session."

# State operations
"Persisted game state for thread {thread_id}"
"Failed to persist game state: {error}"
"No thread_id available; cannot persist game state"

# SSE events
"Received SSE: {event_type}"
```

**Inspect Persisted State:**
```bash
cd /Users/lmy/Projects/Cocai
sqlite3 .chainlit/data.db "SELECT id, metadata FROM threads LIMIT 1;"
```

## Deployment Notes

- **Database Migration:** No new tables needed; uses existing `threads.metadata` column
- **Backward Compatibility:** Gracefully handles missing state (treats as new session)
- **Data Cleanup:** Consider archiving or deleting old threads periodically
- **Monitoring:** Track save/load success rates and latency

## Future Enhancements

1. **Differential Persistence:** Only save changed fields (reduce I/O)
2. **Automatic Cleanup:** Archive threads older than N days
3. **Conflict Resolution:** Handle simultaneous multi-tab edits
4. **State Diff View:** UI to see what changed between saves
5. **Export/Import:** Allow users to export/import game sessions
6. **Undo/Redo:** Maintain state history snapshots
