import asyncio
import logging
import multiprocessing as mp
import os
import signal
from contextlib import asynccontextmanager
from itertools import chain, repeat
from typing import Annotated, List

from chainlit.utils import mount_chainlit
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Template
from sse_starlette.sse import EventSourceResponse

from events import broadcaster
from utils import set_up_logging

set_up_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger("lifespan")
    # Signal to tell long-lived streams (like SSE) to terminate quickly on shutdown
    app.state.shutdown_event = asyncio.Event()
    # Startup
    try:
        # Install signal handlers so the reloader's SIGTERM/SIGINT cleanly stop this app process
        loop = asyncio.get_running_loop()

        async def _graceful_then_exit():
            try:
                logger.info("Signal received: initiating graceful shutdown...")
                if hasattr(app.state, "shutdown_event"):
                    app.state.shutdown_event.set()
                await broadcaster.close()
            except Exception as e:
                logger.error(f"Error during signal shutdown: {e}")
            finally:
                # Last resort: ensure process exits so the reloader doesn't hang
                await asyncio.sleep(0.2)
                os._exit(0)

        def _on_signal():
            asyncio.create_task(_graceful_then_exit())

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _on_signal)
            except NotImplementedError:
                # Fallback for platforms without add_signal_handler
                signal.signal(sig, lambda *_: os._exit(0))
        yield
    finally:
        # Shutdown: close SSE broadcaster so clients disconnect promptly
        try:
            logger.info("Signaling shutdown to SSE streams and broadcaster...")
            # First, signal our shutdown event so generators stop waiting immediately
            app.state.shutdown_event.set()
            # Then, close the broadcaster which will publish a shutdown message
            await broadcaster.close()
        except Exception as e:
            logger.error(f"Error during broadcaster shutdown: {e}")
        # Best-effort cleanup for any multiprocessing children that third-party libs may have spawned
        try:
            children = mp.active_children()
            if children:
                logger.info(
                    f"Terminating {len(children)} multiprocessing child process(es)..."
                )
                for p in children:
                    try:
                        p.terminate()
                    except Exception as te:
                        logger.warning(f"Failed to terminate child {p.pid}: {te}")
                # Give them a moment to exit
                for p in children:
                    try:
                        p.join(timeout=3)
                    except Exception:
                        pass
                # Force kill any that remain alive (Python 3.8+ has kill)
                stubborn = [p for p in children if p.is_alive()]
                for p in stubborn:
                    try:
                        logger.warning(f"Killing stubborn child process {p.pid}...")
                        p.kill()
                    except Exception as ke:
                        logger.error(f"Failed to kill child {p.pid}: {ke}")
        except Exception as e:
            logger.error(f"Error during multiprocessing children cleanup: {e}")


app = FastAPI(lifespan=lifespan)


# Mount the 'static' directory to serve static files
app.mount("/static", StaticFiles(directory="dice/static"), name="static")
# Expose public assets
app.mount("/public", StaticFiles(directory="public"), name="public")

# Template for rendering the dice in the HTML
with open("dice/index.jinja", encoding="utf-8") as _f:
    dice_template = _f.read()


@app.get("/roll_dice", response_class=HTMLResponse)
async def roll_dice(
    # Use List instead of Iterable here, so that multiple values can be passed in the query parameter.
    d4: Annotated[List[int], Query()] = [],
    d6: Annotated[List[int], Query()] = [],
    d8: Annotated[List[int], Query()] = [],
    d10: Annotated[List[int], Query()] = [],
    d12: Annotated[List[int], Query()] = [],
    d20: Annotated[List[int], Query()] = [],
):
    # Prepare a list of dice types and their values
    dice_data = [
        [dice_type, dice_value]
        for dice_type, dice_value in chain.from_iterable(
            [
                zip(repeat("d4"), d4),
                zip(repeat("d6"), d6),
                zip(repeat("d8"), d8),
                zip(repeat("d10"), d10),
                zip(repeat("d12"), d12),
                zip(repeat("d20"), d20),
            ]
        )
    ]
    # Render the template with the dice data passed as context
    template = Template(dice_template)
    return template.render(dice_options=dice_data)


@app.get("/play", response_class=HTMLResponse)
async def play_ui():
    """Serve the new three-column UI."""
    with open("public/play.html", encoding="utf-8") as f:
        return f.read()


@app.get("/api/events")
async def sse_events(request: Request):
    """Server-Sent Events stream using EventSourceResponse for robust handling.
    - Detects client disconnects
    - Responds immediately to app shutdown
    - Sends heartbeats automatically via `ping`
    """
    q = await broadcaster.subscribe()

    async def publisher():
        try:
            while True:
                # End fast on app shutdown
                se = getattr(request.app.state, "shutdown_event", None)
                if se is not None and se.is_set():
                    break
                # End on client disconnect
                try:
                    if await request.is_disconnected():
                        break
                except Exception:
                    pass

                # Wait for next event with small timeout to react to shutdown/disconnect
                try:
                    data = await asyncio.wait_for(q.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue

                if isinstance(data, dict) and data.get("type") == "server_shutdown":
                    break

                # EventSourceResponse expects str/bytes for 'data' or a dict with 'data'
                if isinstance(data, (bytes, bytearray)):
                    yield {"data": data.decode("utf-8", errors="ignore")}
                else:
                    from json import dumps

                    yield {"data": dumps(data, ensure_ascii=False)}
        finally:
            await broadcaster.unsubscribe(q)

    return EventSourceResponse(
        publisher(),
        ping=10000,  # ms
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering
        },
    )


mount_chainlit(app=app, target="main.py", path="/chat")
# To see how dice rolling works, uncomment the following line and comment out the line above.
