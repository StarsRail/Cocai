"""
Vector-based caching for generated scene images using Qdrant.

Stores embeddings of scene descriptions along with their corresponding images
to enable semantic similarity-based cache retrieval. Prevents regenerating
images for semantically similar scene descriptions.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import qdrant_client
from llama_index.core import Settings
from qdrant_client.http import models

logger = logging.getLogger("image_cache")

# Collection name for cached scene images
SCENE_IMAGES_COLLECTION = "scene_images"
SIMILARITY_THRESHOLD = 0.85  # Cosine similarity threshold for cache hits


class ImageCache:
    """Manages vector-based image caching in Qdrant."""

    def __init__(
        self,
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        embedding_dim: int = 768,
    ):
        """
        Initialize the image cache.

        Args:
            qdrant_host: Qdrant server hostname
            qdrant_port: Qdrant server port
            embedding_dim: Dimension of embeddings (default 768 for nomic-embed-text)
        """
        self.qdrant_host = qdrant_host
        self.qdrant_port = qdrant_port
        self.embedding_dim = embedding_dim
        self.client: Optional[qdrant_client.QdrantClient] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize Qdrant client and create collection if needed."""
        if self._initialized:
            return

        try:
            self.client = qdrant_client.QdrantClient(
                host=self.qdrant_host, port=self.qdrant_port
            )
            logger.info(f"Connected to Qdrant at {self.qdrant_host}:{self.qdrant_port}")

            # Create collection if it doesn't exist
            if not self.client.collection_exists(SCENE_IMAGES_COLLECTION):
                logger.info(
                    f"Creating Qdrant collection '{SCENE_IMAGES_COLLECTION}' "
                    f"with {self.embedding_dim}-dim vectors"
                )
                self.client.create_collection(
                    collection_name=SCENE_IMAGES_COLLECTION,
                    vectors_config=models.VectorParams(
                        size=self.embedding_dim, distance=models.Distance.COSINE
                    ),
                )
            else:
                logger.info(
                    f"Using existing Qdrant collection '{SCENE_IMAGES_COLLECTION}'"
                )

            self._initialized = True
        except Exception as e:
            logger.error("Failed to initialize image cache", exc_info=e)
            raise

    async def query_similar_cached_image(
        self, description: str, threshold: float = SIMILARITY_THRESHOLD
    ) -> Optional[str]:
        """
        Query for a cached image similar to the given description.

        Args:
            description: Scene description to search for
            threshold: Minimum cosine similarity score (0-1) for a match

        Returns:
            Path to cached image file if a similar one exists, None otherwise
        """
        if not self._initialized or not self.client:
            return None

        try:
            # Embed the description using LlamaIndex's global embed model
            if not Settings.embed_model:
                logger.warning("No embedding model available in LlamaIndex Settings")
                return None

            embedding = Settings.embed_model.get_text_embedding(description)

            # Search for similar vectors in Qdrant using the HTTP client
            search_results = self.client.search(  # type: ignore
                collection_name=SCENE_IMAGES_COLLECTION,
                query_vector=embedding,
                limit=1,
                score_threshold=threshold,
            )

            if search_results:
                top_hit = search_results[0]
                image_path = top_hit.payload.get("image_path")
                similarity_score = top_hit.score
                logger.info(
                    f"Cache hit: similarity={similarity_score:.3f}, image={image_path}"
                )
                return image_path
            else:
                logger.debug(f"No cache hit for description (threshold={threshold})")
                return None
        except Exception as e:
            logger.warning("Error querying image cache", exc_info=e)
            return None

    async def store_generated_image(
        self, description: str, image_bytes: bytes, image_path: str
    ) -> bool:
        """
        Store a generated image in the cache.

        Args:
            description: Scene description used to generate the image
            image_bytes: Raw image bytes (for validation, not stored)
            image_path: Path where the image was saved (stored as metadata)

        Returns:
            True if successfully stored, False otherwise
        """
        if not self._initialized or not self.client:
            logger.warning("Image cache not initialized")
            return False

        try:
            # Embed the description
            if not Settings.embed_model:
                logger.warning("No embedding model available in LlamaIndex Settings")
                return False

            embedding = Settings.embed_model.get_text_embedding(description)

            # Generate a unique point ID (timestamp-based for simplicity)
            point_id = int(datetime.now(UTC).timestamp() * 1_000_000)

            # Store in Qdrant
            self.client.upsert(  # type: ignore
                collection_name=SCENE_IMAGES_COLLECTION,
                points=[
                    models.PointStruct(
                        id=point_id,
                        vector=embedding,
                        payload={
                            "description": description[:500],  # Store first 500 chars
                            "image_path": image_path,
                            "created_at": datetime.now(UTC).isoformat(),
                        },
                    )
                ],
            )

            logger.info(f"Stored cached image: {image_path} (point_id={point_id})")
            return True
        except Exception as e:
            logger.warning("Error storing in image cache", exc_info=e)
            return False

    async def generate_and_cache_scene_image(
        self,
        description: str,
        width: int = 900,
        height: int = 300,
    ) -> Optional[str]:
        """
        Generate a scene image with caching and disk persistence.

        Combines: cache lookup -> file I/O -> generation -> storage.

        Args:
            description: Scene description to illustrate
            width: Image width in pixels
            height: Image height in pixels

        Returns:
            URL path (e.g., "/public/illustrations/scene-{ts}.png") if successful, None otherwise
        """
        logger_inner = logging.getLogger("generate_and_cache_scene_image")

        try:
            # Step 1: Check cache for similar images
            cached_image_path = await self.query_similar_cached_image(description)
            if cached_image_path:
                try:
                    # Verify file still exists
                    if Path(cached_image_path).exists():
                        logger_inner.info(f"Cache hit: {cached_image_path}")
                        return cached_image_path.replace("public/", "/public/")
                except Exception as e:
                    logger_inner.debug(f"Cached file check failed: {e}")
                    # Fall through to generate new image

            # Step 2: Generate new image
            from .image_generation import generate_image

            logger_inner.info("Cache miss or file not found; generating new image")
            image_bytes = await generate_image(description, width=width, height=height)
            if not image_bytes:
                logger_inner.warning("Image generation failed")
                return None

            # Step 3: Save to disk
            out_dir = Path("public/illustrations")
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            fname = f"scene-{ts}.png"
            file_path = out_dir / fname
            file_path.write_bytes(image_bytes)
            logger_inner.info(f"Saved image to disk: {file_path}")

            # Step 4: Store in cache
            await self.store_generated_image(description, image_bytes, str(file_path))

            return f"/public/illustrations/{fname}"
        except Exception as e:
            logger_inner.warning("Error in generate_and_cache_scene_image", exc_info=e)
            return None


# Global instance (initialized lazily in async context)
_cache_instance: Optional[ImageCache] = None


async def get_cache_instance(
    qdrant_host: str = "localhost", qdrant_port: int = 6333
) -> ImageCache:
    """Get or create the global image cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = ImageCache(qdrant_host=qdrant_host, qdrant_port=qdrant_port)
        await _cache_instance.initialize()
    return _cache_instance
