# Session Persistence: Developer Guide

## Quick Start

### Understanding the System

Session persistence automatically saves game state (clues, history, illustrations, character) to a database and restores it when the user refreshes or returns later.

**Key Files:**

- `game_state/load_and_save.py` - Save/load logic
- `game_state/data_models.py` - GameState model & serialization
- `src/main.py` - Session initialization & broadcasting
- Tools throughout that call `await save_game_state()`

### Accessing Current Game State

From any tool or helper that receives `ctx: Context`:

```python
# Read-only access
read_only_state: GameState = await ctx.store.get("user-visible")

# Modify and persist
async with ctx.store.edit_state() as ctx_state:
    user_visible_state: GameState = ctx_state.get("user-visible")
    user_visible_state.clues.append(new_clue)
    # Changes visible immediately, but NOT persisted until you call:

await save_game_state(user_visible_state)
```

## Common Tasks

### 1. Adding a New Persistent Field

**Scenario:** You want to track `player_inventory: list[str]`

**Step 1:** Update `GameState` dataclass
```python
# game_state/data_models.py
@dataclass
class GameState:
    phase: GamePhase = GamePhase.CHARACTER_CREATION
    history: str = "..."
    clues: list[Clue] = field(default_factory=list)
    illustration_url: str | None = None
    pc: Character | None = None
    player_inventory: list[str] = field(default_factory=list)  # ← NEW
```

**Step 2:** Update serialization
```python
# game_state/data_models.py - in to_dict() method
def to_dict(self) -> dict:
    # ... existing code ...
    return {
        "phase": self.phase.value,
        "history": self.history,
        "clues": [...],
        "illustration_url": self.illustration_url,
        "pc": {...},
        "player_inventory": self.player_inventory,  # ← ADD THIS
    }

# in from_dict() method
@staticmethod
def from_dict(data: dict) -> "GameState":
    # ... existing code ...
    return GameState(
        phase=phase,
        history=data.get("history", ""),
        clues=clues,
        illustration_url=data.get("illustration_url"),
        pc=None,
        player_inventory=data.get("player_inventory", []),  # ← ADD THIS
    )
```

**Step 3:** Send in session start
```python
# src/main.py - in @cl.on_chat_start factory()
game_state_dict = user_visible_game_state.to_dict()
await cl.send_window_message({"type": "inventory", "items": game_state_dict.get("player_inventory", [])})

# play.js will receive {"type": "inventory", "items": [...]}
```

**Step 4:** Save after mutations
```python
# In your tool
async with ctx.store.edit_state() as ctx_state:
    user_visible_state: GameState = ctx_state.get("user-visible")
    user_visible_state.player_inventory.append("Gold Coin")

await save_game_state(user_visible_state)
await cl.send_window_message({"type": "inventory", "items": user_visible_state.player_inventory})
```

### 2. Inspecting a User's Persisted State

```python
# From a Chainlit session, get the thread ID
import chainlit as cl
thread_id = cl.context.session.thread_id

# Query the database
from utils import set_up_data_layer
data_layer = set_up_data_layer()
thread = await data_layer.get_thread(thread_id)

# Extract game state
game_state_dict = thread.metadata.get("game_state", {})
print(f"History: {game_state_dict.get('history')}")
print(f"Clues: {game_state_dict.get('clues')}")
print(f"Character: {game_state_dict.get('pc', {}).get('name')}")
```

### 3. Manually Resetting a User's State

```python
# Clear a user's game state
import chainlit as cl
from load_and_save import save_game_state
from state import GameState

# Create fresh state
fresh_state = GameState()

# Save it
await save_game_state(fresh_state)

# Send to UI
await cl.send_window_message({"type": "history", "history": ""})
await cl.send_window_message({"type": "clues", "clues": []})
await cl.send_window_message({"type": "pc", "pc": {}})
```

### 4. Exporting a User's Game State

```python
import json
from load_and_save import load_game_state

# Load user's state
state = await load_game_state()

if state:
    exported = state.to_dict()
    json_str = json.dumps(exported, indent=2)
    # Save to file, send to user, etc.
    with open(f"export_{thread_id}.json", "w") as f:
        f.write(json_str)
```

### 5. Importing a Saved Game State

```python
import json
from state import GameState
from load_and_save import save_game_state

# Load from file
with open("export_abc123.json", "r") as f:
    data = json.load(f)

# Reconstruct state
state = GameState.from_dict(data)

# Save to database
await save_game_state(state)

# Send to UI
await cl.send_window_message({"type": "history", "history": state.history})
await cl.send_window_message({"type": "clues", "clues": [c.__dict__ for c in state.clues]})
```

## Testing Persistence

### Unit Test: Serialization Round-Trip

```python
# tests/test_persistence.py
import pytest
from state import GameState, Clue

@pytest.mark.asyncio
async def test_game_state_serialization():
    """Ensure GameState survives to_dict/from_dict cycle"""
    original = GameState(
        history="The story so far...",
        clues=[Clue(id="c1", title="Clue 1", content="Details")],
    )

    # Serialize
    data = original.to_dict()

    # Deserialize
    restored = GameState.from_dict(data)

    # Compare (note: Character object will be None)
    assert restored.history == original.history
    assert len(restored.clues) == 1
    assert restored.clues[0].title == "Clue 1"
```

### Integration Test: Persistence Layer

```python
@pytest.mark.asyncio
async def test_load_nonexistent_state():
    """Gracefully handles missing state"""
    state = await load_game_state()
    # Should return None without crashing
    assert state is None
```

### Manual Test: End-to-End

1. Start server: `just serve`
2. Open http://localhost:8000/play
3. Create character
4. Add a clue (via agent tool)
5. Close browser completely
6. Open http://localhost:8000/play again
7. **Verify:** Character, clue, and history are present

## Debugging

### Check if State is Saving

Add temporary logging:
```python
# In load_and_save.py
async def save_game_state(game_state: GameState) -> bool:
    logger.info(f"SAVING: history={game_state.history[:50]}...")
    logger.info(f"SAVING: {len(game_state.clues)} clues")
    # ... rest of function
```

### Fixing: "AttributeError: 'function' object has no attribute 'get_thread'"

**Error:** This occurs when `load_and_save.py` tries to call `data_layer.get_thread()` but data_layer is actually a function/decorator, not the data layer instance.

**Root Cause:** Don't try to store the data layer in `cl.user_session`. The `cl.data_layer` decorator is not meant to be used this way.

**Solution:** Import `set_up_data_layer` directly in `load_and_save.py`:
```python
from utils import set_up_data_layer

async def save_game_state(game_state: GameState) -> bool:
    # ...
    data_layer = set_up_data_layer()  # Call it directly, don't store it
    thread = await data_layer.get_thread(thread_id)
    # ...
```

This is the correct approach because:
1. `set_up_data_layer()` creates a fresh data layer instance each time
2. Chainlit properly manages the connection lifecycle
3. No need to manage storage across sessions

### Inspect Database

```bash
# View all threads
sqlite3 .chainlit/data.db "SELECT id, name FROM threads;"

# View metadata for a specific thread
sqlite3 .chainlit/data.db \
  "SELECT id, metadata FROM threads WHERE id='<thread-id>';" | head -20

# Pretty print (requires jq)
sqlite3 .chainlit/data.db "SELECT metadata FROM threads LIMIT 1;" | jq .
```

### Check Window Messages

Open browser DevTools → Console tab. Window messages from Chainlit will be visible when you add a listener. You should see events like:
```json
{"type": "history", "history": "..."}
{"type": "clues", "clues": [...]}
{"type": "pc", "pc": {"name": "...", "stats": {...}}}
```

### Verify Data Layer Connection

```python
import chainlit as cl
from utils import set_up_data_layer

data_layer = set_up_data_layer()
print(f"Data layer: {data_layer}")
print(f"DB type: {data_layer.__class__.__name__}")
```

## Common Issues & Solutions

### Issue: State not persisting after creation

**Symptoms:** Create character, refresh page, character gone

**Check:**
1. Is `await save_game_state()` being called?
   ```python
   # Verify in create_character.py after state mutation
   await save_game_state(user_visible_state)  # ← Must be present
   ```

2. Are there database errors?
   ```bash
   # Check logs for "Failed to persist game state"
   grep -r "Failed to persist" logs/
   ```

3. Is thread_id available?
   ```python
   thread_id = cl.context.session.thread_id
   assert thread_id, "No thread_id found!"
   ```

### Issue: "AttributeError: 'function' object has no attribute 'get_thread'"

**Symptoms:** Error in logs after character creation or state mutations: `Failed to persist game state: 'function' object has no attribute 'get_thread'`

**Root Cause:** Code tried to use `cl.user_session.get("data_layer")` which returns the decorator function, not an actual data layer instance.

**Solution:** Don't store the data layer in user_session. Instead, import and call `set_up_data_layer()` directly in `load_and_save.py`:
```python
# ✅ CORRECT
from utils import set_up_data_layer

async def save_game_state(game_state: GameState) -> bool:
    # ...
    data_layer = set_up_data_layer()  # Call it to get the instance
    thread = await data_layer.get_thread(thread_id)
```

And remove this from `main.py`:
```python
# ❌ REMOVE THIS:
data_layer = cl.data_layer  # This is a decorator, not the instance!
cl.user_session.set("data_layer", data_layer)
```

The fix ensures we always get a fresh, properly-initialized data layer instance.

### Issue: State loads but doesn't render in UI

**Symptoms:** Page refreshes, nothing shows in panes

**Check:**
1. Are window messages being sent in `@cl.on_chat_start`?
   ```python
   # In main.py, verify these cl.send_window_message() calls exist
   await cl.send_window_message({"type": "history", ...})
   await cl.send_window_message({"type": "clues", ...})
   ```

2. Is play.js listening?
   ```javascript
   // In DevTools console while on /play
   window.addEventListener('message', (ev) => console.log("Window message:", ev.data))
   ```

3. Is state dict well-formed?
   ```python
   game_state_dict = state.to_dict()
   print(json.dumps(game_state_dict, indent=2))
   ```

### Issue: Character not restoring

**Expected behavior:** UI shows character name/stats, but not the full Character object (that's not persisted)

**This is by design:** cochar.Character objects can't be serialized reliably, so only the UI representation is saved. The actual Character object would need to be reconstructed by the agent.

## Performance Tuning

### Reducing Save Frequency

If you're concerned about database write overhead:

```python
# Option 1: Batch updates
# Instead of saving after every clue, collect multiple and save once

# Option 2: Debounce
# Save only if X seconds have passed since last save
```

### Monitoring Save Latency

Add timing:
```python
import time
async def save_game_state(game_state: GameState) -> bool:
    start = time.time()
    # ... save logic ...
    elapsed = (time.time() - start) * 1000
    logger.debug(f"save_game_state took {elapsed:.1f}ms")
    return True
```

## FAQ

**Q: Will session data persist if the server restarts?**
A: Yes. Data is stored in SQLite (`.chainlit/data.db`), so it survives server restarts.

**Q: Can users access each other's game state?**
A: No. Each user/session gets a unique `thread_id`, and state is isolated by thread.

**Q: How long is state retained?**
A: Indefinitely, until manually deleted. Consider implementing a TTL or archive strategy for long-term deployments.

**Q: Why isn't the Character object persisted?**
A: cochar.Character has complex internal state and no built-in serialization. Only the UI representation (stats dict) is recoverable. Full character recreation requires agent involvement.

**Q: Can I export game saves for backup?**
A: Yes, use `to_dict()` to export as JSON. See "Exporting a User's Game State" above.

**Q: What happens if save fails silently?**
A: Logger will emit an error. UI won't show the latest update. Consider adding error alerts to prompt users to retry.

## Resources

- [Session Persistence Architecture](session-persistence.md) - Detailed design
- [GameState Model](../game_state/data_models.py) - Data structure
- [Storage Layer](../game_state/load_and_save.py) - Implementation
- [Chainlit Data Persistence Docs](https://docs.chainlit.io/data-persistence)
