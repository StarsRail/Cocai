import logging
from contextlib import asynccontextmanager
from itertools import chain, repeat
from typing import Annotated, List

from chainlit.utils import mount_chainlit
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Template

from events import broadcaster
from state import STATE
from utils import set_up_logging

set_up_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger("lifespan")
    # Startup
    try:
        yield
    finally:
        # Shutdown: close SSE broadcaster so clients disconnect promptly
        try:
            from events import broadcaster

            logger.info("Waiting for broadcaster to shut down...")
            await broadcaster.close()
        except Exception as e:
            logger.error(f"Error during broadcaster shutdown: {e}")


app = FastAPI(lifespan=lifespan)


# Mount the 'static' directory to serve static files
app.mount("/static", StaticFiles(directory="dice/static"), name="static")
# Expose public assets
app.mount("/public", StaticFiles(directory="public"), name="public")

# Template for rendering the dice in the HTML
dice_template = open("dice/index.jinja").read()


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


@app.get("/api/state")
async def get_state():
    """Used by the UI to fetch the current game state at page load."""
    return JSONResponse(STATE.to_dict())


@app.get("/api/events")
async def sse_events():
    """Server-Sent Events stream for live UI updates. Clients should connect to this endpoint and listen for updates."""
    q = await broadcaster.subscribe()
    return StreamingResponse(
        broadcaster.sse(q),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering
        },
    )


mount_chainlit(app=app, target="main.py", path="/chat")
# To see how dice rolling works, uncomment the following line and comment out the line above.
