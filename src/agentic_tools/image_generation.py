"""
Shared image generation utilities for OpenRouter and Stable Diffusion APIs.

This module centralizes all image generation logic to avoid duplication.
Both illustrate_a_scene and auto_scene_update use these functions.
"""

import base64
import logging
import os
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)


def _extract_base64_from_data_url(data_url: str) -> bytes:
    """Extract and decode base64 from a data URL."""
    if data_url.startswith("data:"):
        # Format: data:image/png;base64,<base64_data>
        base64_part = data_url.split(",", 1)[1]
        return base64.b64decode(base64_part)
    else:
        # Assume it's raw base64
        return base64.b64decode(data_url)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.5, max=3),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
)
async def generate_image_with_openrouter(
    scene_description: str,
    api_key: str,
) -> bytes:
    """Generate an image using OpenRouter API and return raw image bytes."""
    logger = logging.getLogger("generate_image_with_openrouter")
    model = os.environ.get("OPENROUTER_IMG_GEN_LLM_ID", "sourceful/riverflow-v2-pro")
    logger.info(f"Using OpenRouter model: {model}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": scene_description,
                    }
                ],
                "modalities": ["image"],
            },
        )
        response.raise_for_status()
        data = response.json()

    if not data.get("choices") or not data["choices"][0].get("message", {}).get(
        "images"
    ):
        raise ValueError("No images in OpenRouter response")

    image_data = _extract_base64_from_data_url(
        data["choices"][0]["message"]["images"][0]["image_url"]["url"]
    )
    return image_data


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.5, max=3),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
)
async def generate_image_with_stable_diffusion(
    scene_description: str,
    width: int = 768,
    height: int = 512,
) -> bytes:
    """Generate an image using Stable Diffusion API and return raw image bytes."""
    logger = logging.getLogger("generate_image_with_stable_diffusion")
    base_url = os.environ.get("STABLE_DIFFUSION_API_URL", "http://127.0.0.1:7860")
    logger.debug(f"Using Stable Diffusion at {base_url} with size {width}x{height}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/sdapi/v1/txt2img",
            headers={
                "accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "prompt": scene_description,
                "negative_prompt": "",
                "sampler": "DPM++ SDE",
                "scheduler": "Automatic",
                "steps": 6,
                "cfg_scale": 2,
                "width": width,
                "height": height,
            },
        )
        response.raise_for_status()
        data = response.json()

    b64_image = (data or {}).get("images", [None])[0]
    if not b64_image:
        raise ValueError("No images in Stable Diffusion response")

    return base64.b64decode(b64_image)


async def generate_image(
    scene_description: str,
    width: int = 768,
    height: int = 512,
) -> bytes | None:
    """
    Generate an image with automatic fallback logic.

    Tries OpenRouter first if API key is available, then falls back to Stable Diffusion.
    Returns None if no service is available or all services fail.
    """
    logger = logging.getLogger("generate_image")

    # Try OpenRouter first if API key is available
    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_api_key:
        logger.info("Attempting to generate image using OpenRouter.")
        try:
            return await generate_image_with_openrouter(
                scene_description, openrouter_api_key
            )
        except Exception as e:
            logger.warning(
                "OpenRouter image generation failed; falling back to Stable Diffusion.",
                exc_info=e,
            )

    # Fall back to Stable Diffusion
    try:
        logger.info("Attempting to generate image using Stable Diffusion.")
        return await generate_image_with_stable_diffusion(
            scene_description, width=width, height=height
        )
    except Exception as e:
        logger.warning("Image generation service unavailable.", exc_info=e)
        return None


async def generate_image_with_cache(
    scene_description: str,
    width: int = 768,
    height: int = 512,
    qdrant_host: str = "localhost",
    qdrant_port: int = 6333,
) -> bytes | None:
    """
    Generate an image with vector-based caching.

    Flow:
    1. Query cache for semantically similar cached images
    2. If found (similarity >= threshold), return cached image bytes
    3. If not found, generate new image via generate_image()
    4. Store generated image in cache for future lookups
    5. Return image bytes

    Args:
        scene_description: Description of the scene to illustrate
        width: Image width (used only if generating new image)
        height: Image height (used only if generating new image)
        qdrant_host: Qdrant server hostname
        qdrant_port: Qdrant server port

    Returns:
        Image bytes if successful, None if generation/caching fails
    """
    logger = logging.getLogger("generate_image_with_cache")

    try:
        # Import here to avoid circular imports
        from .image_cache import get_cache_instance

        cache = await get_cache_instance(
            qdrant_host=qdrant_host, qdrant_port=qdrant_port
        )

        # Step 1: Check cache for similar images
        cached_image_path = await cache.query_similar_cached_image(scene_description)
        if cached_image_path:
            try:
                # Try to read cached image from disk
                image_bytes = Path(cached_image_path).read_bytes()
                logger.info(f"Returning cached image: {cached_image_path}")
                return image_bytes
            except FileNotFoundError:
                logger.warning(f"Cached image file not found: {cached_image_path}")
                # Fall through to generate new image
            except Exception as e:
                logger.warning(
                    f"Error reading cached image: {cached_image_path}", exc_info=e
                )
                # Fall through to generate new image

        # Step 2: Generate new image
        logger.info("Cache miss or read error; generating new image.")
        maybe_image_bytes = await generate_image(
            scene_description, width=width, height=height
        )
        if not maybe_image_bytes:
            logger.warning("Failed to generate image.")
            return None

        # Step 3: Save to disk (caller's responsibility in most cases,
        # but we store path in cache; for caching, we assume caller saves it first)
        # Store in cache with a placeholder path that will be updated if caller saves
        await cache.store_generated_image(
            scene_description,
            maybe_image_bytes,
            "[in-memory-only]",
        )

        return maybe_image_bytes
    except Exception as e:
        logger.warning("Error in generate_image_with_cache", exc_info=e)
        # Fall back to non-cached generation
        return await generate_image(scene_description, width=width, height=height)


async def store_image_in_cache(
    scene_description: str,
    image_path: str,
    qdrant_host: str = "localhost",
    qdrant_port: int = 6333,
) -> bool:
    """
    Store a generated image in the cache after it's been saved to disk.

    This is a companion function to generate_image_with_cache for cases where
    the caller explicitly saves the image and wants to index it.

    Args:
        scene_description: Description of the scene
        image_path: Path where the image was saved
        qdrant_host: Qdrant server hostname
        qdrant_port: Qdrant server port

    Returns:
        True if successfully stored, False otherwise
    """
    try:
        from .image_cache import get_cache_instance

        cache = await get_cache_instance(
            qdrant_host=qdrant_host, qdrant_port=qdrant_port
        )
        return await cache.store_generated_image(
            scene_description,
            b"",
            image_path,  # Pass empty bytes, only path matters
        )
    except Exception as e:
        logger = logging.getLogger("store_image_in_cache")
        logger.warning("Error storing image in cache", exc_info=e)
        return False
