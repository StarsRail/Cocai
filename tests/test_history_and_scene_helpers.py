import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from async_panes import history, scene


class DummyAsyncClient:
    """Minimal async context manager to mock httpx.AsyncClient."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):  # type: ignore[override]
        class Resp:
            def raise_for_status(self):
                return None

            def json(self):  # noqa: D401 - simple stub
                # 1x1 transparent PNG
                png_bytes = (
                    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
                    b"\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x05\x00\x01"
                    b"\x0d\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
                )
                return {"images": [base64.b64encode(png_bytes).decode("utf-8")]}

        return Resp()


def _future_with(value: str):
    fut: asyncio.Future[str] = asyncio.Future()
    fut.set_result(value)
    return fut


@pytest.mark.asyncio
async def test_should_update_history_yes(monkeypatch):
    monkeypatch.setattr(
        history, "llm_complete_text", lambda prompt: _future_with("YES")
    )
    assert await history.__should_update_history([{"role": "user", "content": "hi"}])  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_should_update_history_no(monkeypatch):
    monkeypatch.setattr(history, "llm_complete_text", lambda prompt: _future_with("NO"))
    assert not await history.__should_update_history(
        [{"role": "user", "content": "hi"}]
    )  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_should_update_scene_and_generate_image(monkeypatch):
    # Force YES and provide description
    monkeypatch.setattr(scene, "llm_complete_text", lambda prompt: _future_with("YES"))
    monkeypatch.setattr(
        scene,
        "__describe_visual_scene",
        lambda transcript: _future_with("A dark library with flickering candles."),  # type: ignore[attr-defined]
    )
    monkeypatch.setattr(scene, "httpx", SimpleNamespace(AsyncClient=DummyAsyncClient))

    class DummyCtxStore:
        def __init__(self):
            self.data = {"user-visible": SimpleNamespace(illustration_url=None)}

        async def edit_state(self):
            outer = self

            class CtxMgr:
                async def __aenter__(self):  # noqa: D401
                    return outer

                async def __aexit__(self, exc_type, exc, tb):  # noqa: D401
                    return False

                def get(self, key):  # noqa: D401
                    return outer.data[key]

            return CtxMgr()

    dummy_ctx = SimpleNamespace(store=DummyCtxStore())
    monkeypatch.setattr(
        scene, "build_transcript", lambda **_: [{"role": "user", "content": "Go"}]
    )
    # Cache list of existing illustrations
    existing = set(Path("public/illustrations").glob("scene-*.png"))
    # Provide an opaque memory object; build_transcript is patched so internals won't access it.
    await scene.update_scene_if_needed(dummy_ctx, memory=object(), last_user_msg="hi")  # type: ignore[arg-type]
    # Check that a new illustration file was created.
    new_files = set(Path("public/illustrations").glob("scene-*.png")) - existing
    assert new_files
    # Clean up created file.
    for f in new_files:
        f.unlink()


@pytest.mark.asyncio
async def test_describe_visual_scene_truncation(monkeypatch):
    long_text = "word " * 400  # > 600 chars
    monkeypatch.setattr(
        scene, "llm_complete_text", lambda prompt: _future_with(long_text)
    )
    desc = await scene.__describe_visual_scene([])  # type: ignore[attr-defined]
    assert len(desc) <= 600
