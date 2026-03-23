"""Tests for agentic_tools.image_cache."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentic_tools.image_cache import (
    SCENE_IMAGES_COLLECTION,
    SIMILARITY_THRESHOLD,
    ImageCache,
    get_cache_instance,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cache(**kwargs) -> ImageCache:
    return ImageCache(
        qdrant_host=kwargs.get("qdrant_host", "localhost"),
        qdrant_port=kwargs.get("qdrant_port", 6333),
        embedding_dim=kwargs.get("embedding_dim", 768),
    )


def _make_qdrant_client(collection_exists: bool = False) -> MagicMock:
    client = MagicMock()
    client.collection_exists.return_value = collection_exists
    return client


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


def test_default_constructor_values():
    cache = _make_cache()
    assert cache.qdrant_host == "localhost"
    assert cache.qdrant_port == 6333
    assert cache.embedding_dim == 768
    assert cache.client is None
    assert cache._initialized is False


def test_custom_constructor_values():
    cache = _make_cache(qdrant_host="remote", qdrant_port=9999, embedding_dim=384)
    assert cache.qdrant_host == "remote"
    assert cache.qdrant_port == 9999
    assert cache.embedding_dim == 384


# ---------------------------------------------------------------------------
# initialize()
# ---------------------------------------------------------------------------


async def test_initialize_creates_collection_when_absent():
    cache = _make_cache()
    mock_client = _make_qdrant_client(collection_exists=False)

    with patch(
        "agentic_tools.image_cache.qdrant_client.QdrantClient", return_value=mock_client
    ):
        await cache.initialize()

    assert cache._initialized is True
    mock_client.create_collection.assert_called_once()
    call_kwargs = mock_client.create_collection.call_args.kwargs
    assert call_kwargs["collection_name"] == SCENE_IMAGES_COLLECTION
    assert call_kwargs["vectors_config"].size == 768


async def test_initialize_skips_creation_when_collection_exists():
    cache = _make_cache()
    mock_client = _make_qdrant_client(collection_exists=True)

    with patch(
        "agentic_tools.image_cache.qdrant_client.QdrantClient", return_value=mock_client
    ):
        await cache.initialize()

    assert cache._initialized is True
    mock_client.create_collection.assert_not_called()


async def test_initialize_is_idempotent():
    cache = _make_cache()
    mock_client = _make_qdrant_client(collection_exists=False)

    with patch(
        "agentic_tools.image_cache.qdrant_client.QdrantClient", return_value=mock_client
    ):
        await cache.initialize()
        await cache.initialize()  # second call should be a no-op

    # QdrantClient constructor called only once
    assert mock_client.collection_exists.call_count == 1


async def test_initialize_propagates_connection_error():
    cache = _make_cache()

    with patch(
        "agentic_tools.image_cache.qdrant_client.QdrantClient",
        side_effect=ConnectionRefusedError("no qdrant"),
    ):
        with pytest.raises(ConnectionRefusedError):
            await cache.initialize()

    assert cache._initialized is False


# ---------------------------------------------------------------------------
# query_similar_cached_image()
# ---------------------------------------------------------------------------


async def test_query_returns_none_when_not_initialized():
    cache = _make_cache()
    result = await cache.query_similar_cached_image("some description")
    assert result is None


async def test_query_returns_none_when_no_embed_model():
    cache = _make_cache()
    cache._initialized = True
    cache.client = MagicMock()

    with patch("agentic_tools.image_cache.Settings") as mock_settings:
        mock_settings.embed_model = None
        result = await cache.query_similar_cached_image("some description")

    assert result is None


async def test_query_returns_path_on_cache_hit():
    cache = _make_cache()
    cache._initialized = True
    mock_client = MagicMock()
    cache.client = mock_client

    hit = MagicMock()
    hit.payload = {"image_path": "public/illustrations/scene-abc.png"}
    hit.score = 0.95
    mock_client.search.return_value = [hit]

    mock_embed_model = MagicMock()
    mock_embed_model.get_text_embedding.return_value = [0.1] * 768

    with patch("agentic_tools.image_cache.Settings") as mock_settings:
        mock_settings.embed_model = mock_embed_model
        result = await cache.query_similar_cached_image("a rainy street")

    assert result == "public/illustrations/scene-abc.png"
    mock_client.search.assert_called_once_with(
        collection_name=SCENE_IMAGES_COLLECTION,
        query_vector=[0.1] * 768,
        limit=1,
        score_threshold=SIMILARITY_THRESHOLD,
    )


async def test_query_returns_none_on_cache_miss():
    cache = _make_cache()
    cache._initialized = True
    mock_client = MagicMock()
    cache.client = mock_client
    mock_client.search.return_value = []

    mock_embed_model = MagicMock()
    mock_embed_model.get_text_embedding.return_value = [0.0] * 768

    with patch("agentic_tools.image_cache.Settings") as mock_settings:
        mock_settings.embed_model = mock_embed_model
        result = await cache.query_similar_cached_image("foggy alley")

    assert result is None


async def test_query_returns_none_on_exception():
    cache = _make_cache()
    cache._initialized = True
    mock_client = MagicMock()
    cache.client = mock_client
    mock_client.search.side_effect = RuntimeError("qdrant blew up")

    mock_embed_model = MagicMock()
    mock_embed_model.get_text_embedding.return_value = [0.0] * 768

    with patch("agentic_tools.image_cache.Settings") as mock_settings:
        mock_settings.embed_model = mock_embed_model
        result = await cache.query_similar_cached_image("description")

    assert result is None


# ---------------------------------------------------------------------------
# store_generated_image()
# ---------------------------------------------------------------------------


async def test_store_returns_false_when_not_initialized():
    cache = _make_cache()
    result = await cache.store_generated_image("desc", b"bytes", "/path/img.png")
    assert result is False


async def test_store_returns_false_when_no_embed_model():
    cache = _make_cache()
    cache._initialized = True
    cache.client = MagicMock()

    with patch("agentic_tools.image_cache.Settings") as mock_settings:
        mock_settings.embed_model = None
        result = await cache.store_generated_image("desc", b"bytes", "/path/img.png")

    assert result is False


async def test_store_returns_true_on_success():
    cache = _make_cache()
    cache._initialized = True
    mock_client = MagicMock()
    cache.client = mock_client

    mock_embed_model = MagicMock()
    mock_embed_model.get_text_embedding.return_value = [0.2] * 768

    with patch("agentic_tools.image_cache.Settings") as mock_settings:
        mock_settings.embed_model = mock_embed_model
        result = await cache.store_generated_image(
            "sunset over the docks", b"\x89PNG...", "public/illustrations/scene-xyz.png"
        )

    assert result is True
    mock_client.upsert.assert_called_once()
    call_kwargs = mock_client.upsert.call_args.kwargs
    assert call_kwargs["collection_name"] == SCENE_IMAGES_COLLECTION
    point = call_kwargs["points"][0]
    assert point.payload["image_path"] == "public/illustrations/scene-xyz.png"
    assert point.payload["description"] == "sunset over the docks"


async def test_store_truncates_long_descriptions():
    cache = _make_cache()
    cache._initialized = True
    mock_client = MagicMock()
    cache.client = mock_client

    mock_embed_model = MagicMock()
    mock_embed_model.get_text_embedding.return_value = [0.0] * 768
    long_desc = "x" * 1000

    with patch("agentic_tools.image_cache.Settings") as mock_settings:
        mock_settings.embed_model = mock_embed_model
        await cache.store_generated_image(long_desc, b"bytes", "img.png")

    point = mock_client.upsert.call_args.kwargs["points"][0]
    assert len(point.payload["description"]) == 500


async def test_store_returns_false_on_exception():
    cache = _make_cache()
    cache._initialized = True
    mock_client = MagicMock()
    cache.client = mock_client
    mock_client.upsert.side_effect = RuntimeError("upsert failed")

    mock_embed_model = MagicMock()
    mock_embed_model.get_text_embedding.return_value = [0.0] * 768

    with patch("agentic_tools.image_cache.Settings") as mock_settings:
        mock_settings.embed_model = mock_embed_model
        result = await cache.store_generated_image("desc", b"bytes", "img.png")

    assert result is False


# ---------------------------------------------------------------------------
# generate_and_cache_scene_image()
# ---------------------------------------------------------------------------


async def test_generate_returns_cached_path_when_file_exists():
    cache = _make_cache()
    cached = "public/illustrations/scene-cached.png"
    cache.query_similar_cached_image = AsyncMock(return_value=cached)

    with patch("pathlib.Path.exists", return_value=True):
        result = await cache.generate_and_cache_scene_image("dark hallway")

    assert result == "/public/illustrations/scene-cached.png"


async def test_generate_falls_through_when_cached_file_missing(tmp_path):
    """Cache reported a hit but file no longer exists → generate new image."""
    cache = _make_cache()
    cache.query_similar_cached_image = AsyncMock(
        return_value=str(tmp_path / "gone.png")  # file doesn't exist
    )
    cache.store_generated_image = AsyncMock(return_value=True)

    fake_bytes = b"\x89PNG\r\n"

    with (
        patch(
            "agentic_tools.image_generation.generate_image",
            new=AsyncMock(return_value=fake_bytes),
        ),
        patch("pathlib.Path.mkdir"),
        patch("pathlib.Path.write_bytes"),
    ):
        result = await cache.generate_and_cache_scene_image("misty road")

    assert result is not None
    assert result.startswith("/public/illustrations/")
    cache.store_generated_image.assert_awaited_once()


async def test_generate_returns_none_when_image_generation_fails():
    cache = _make_cache()
    cache.query_similar_cached_image = AsyncMock(return_value=None)

    with patch(
        "agentic_tools.image_generation.generate_image",
        new=AsyncMock(return_value=None),
    ):
        result = await cache.generate_and_cache_scene_image("broken scene")

    assert result is None


async def test_generate_returns_none_on_unexpected_exception():
    cache = _make_cache()
    cache.query_similar_cached_image = AsyncMock(side_effect=RuntimeError("boom"))

    result = await cache.generate_and_cache_scene_image("explosion")

    assert result is None


# ---------------------------------------------------------------------------
# get_cache_instance()
# ---------------------------------------------------------------------------


async def test_get_cache_instance_creates_singleton():
    import agentic_tools.image_cache as ic_module

    original = ic_module._cache_instance
    ic_module._cache_instance = None  # reset for isolation

    try:
        with patch.object(ImageCache, "initialize", new=AsyncMock()):
            instance1 = await get_cache_instance()
            instance2 = await get_cache_instance()

        assert instance1 is instance2
        assert isinstance(instance1, ImageCache)
    finally:
        ic_module._cache_instance = original


async def test_get_cache_instance_passes_host_and_port():
    import agentic_tools.image_cache as ic_module

    original = ic_module._cache_instance
    ic_module._cache_instance = None

    try:
        with patch.object(ImageCache, "initialize", new=AsyncMock()):
            instance = await get_cache_instance(qdrant_host="myhost", qdrant_port=1234)

        assert instance.qdrant_host == "myhost"
        assert instance.qdrant_port == 1234
    finally:
        ic_module._cache_instance = original
