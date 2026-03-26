"""
Semantic search service for querying indexed objects.

This module provides natural language search capabilities over indexed
RADOS objects using vector similarity.
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from core.rados_client import RadosClient
from core.embedding_generator import EmbeddingGenerator
from core.rados_vector_store import RadosVectorStore
from core.metadata_schema import SearchResult, SearchQuery

logger = logging.getLogger(__name__)


class Searcher:
    """
    Service for semantic search over indexed objects.

    Provides natural language query capabilities using vector similarity
    search with optional metadata filtering.
    """

    def __init__(
        self,
        rados_client: RadosClient,
        embedding_generator: EmbeddingGenerator,
        vector_store: RadosVectorStore
    ):
        """
        Initialize searcher.

        Args:
            rados_client: RADOS client instance
            embedding_generator: Embedding generator instance
            vector_store: Vector store instance
        """
        self.rados_client = rados_client
        self.embedding_generator = embedding_generator
        self.vector_store = vector_store

        logger.info("Initialized Searcher service")

    def search(
        self,
        query_text: str,
        top_k: int = 10,
        min_score: float = 0.0,
        pool_name: Optional[str] = None,
        content_type: Optional[str] = None,
        include_content: bool = False
    ) -> List[SearchResult]:
        """
        Search for objects matching the query.

        Args:
            query_text: Natural language query
            top_k: Number of results to return
            min_score: Minimum relevance score (0-1)
            pool_name: Filter by pool name (post-filter)
            content_type: Filter by content type (post-filter)
            include_content: Whether to include full content

        Returns:
            List of SearchResult objects ordered by relevance
        """
        logger.info(f"Searching for: '{query_text}' (top_k={top_k})")

        try:
            # Generate query embedding
            query_embedding = self.embedding_generator.encode(query_text)

            # Perform vector search — returns list of dicts with
            # 'object_name', 'similarity', 'preview'
            raw_results = self.vector_store.search(
                query_embedding=query_embedding,
                top_k=top_k,
                min_similarity=min_score,
            )

            # Convert to SearchResult objects
            search_results = []

            for hit in raw_results:
                obj_name = hit["object_name"]
                similarity = hit["similarity"]
                preview = hit.get("preview", "")

                # Fetch full metadata from xattrs
                meta = self.vector_store.get_embedding_metadata(obj_name)
                extra = meta.get("metadata", {})

                # Post-filter on pool / content_type if requested
                if pool_name and extra.get("pool_name") != pool_name:
                    continue
                if content_type and extra.get("content_type") != content_type:
                    continue

                # Parse indexed_at timestamp
                indexed_at = None
                if "indexed_at" in meta:
                    try:
                        indexed_at = datetime.fromisoformat(meta["indexed_at"])
                    except Exception:
                        pass

                keywords = [k for k in extra.get("keywords", "").split(",") if k]
                tags = [t for t in extra.get("tags", "").split(",") if t]

                result = SearchResult(
                    object_id=obj_name,
                    object_name=obj_name,
                    pool_name=extra.get("pool_name", ""),
                    relevance_score=similarity,
                    distance=1.0 - similarity,
                    content_preview=preview,
                    summary=extra.get("summary") or None,
                    keywords=keywords,
                    tags=tags,
                    content_type=extra.get("content_type", ""),
                    size_bytes=int(extra.get("size_bytes", 0)),
                    indexed_at=indexed_at,
                )

                # Optionally fetch full content
                if include_content:
                    try:
                        self.rados_client.ensure_connected()
                        data = self.rados_client.read_object(obj_name)
                        result.full_content = data.decode("utf-8", errors="ignore")
                    except Exception as e:
                        logger.warning(f"Could not fetch content for {obj_name}: {e}")

                search_results.append(result)

            logger.info(f"Found {len(search_results)} results")
            return search_results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise

    def search_by_query(self, query: SearchQuery) -> List[SearchResult]:
        """
        Search using a SearchQuery object.

        Args:
            query: SearchQuery object with all parameters

        Returns:
            List of SearchResult objects
        """
        return self.search(
            query_text=query.query_text,
            top_k=query.top_k,
            min_score=query.min_score,
            pool_name=query.pool_name,
            content_type=query.content_type,
            include_content=query.include_content,
        )

    def find_similar(
        self,
        object_name: str,
        top_k: int = 10,
        exclude_self: bool = True
    ) -> List[SearchResult]:
        """
        Find objects similar to a given object.

        Args:
            object_name: Name of the reference object
            top_k: Number of similar objects to return
            exclude_self: Whether to exclude the reference object

        Returns:
            List of similar objects
        """
        logger.info(f"Finding similar objects to: {object_name}")

        try:
            # Get embedding directly from xattrs
            embedding = self.vector_store.get_embedding(object_name)
            if embedding is None:
                logger.error(f"Object {object_name} not found in index")
                raise ValueError(f"Object {object_name} not indexed")

            # Search with the embedding
            raw_results = self.vector_store.search(
                query_embedding=embedding,
                top_k=top_k + 1 if exclude_self else top_k,
            )

            search_results = []

            for hit in raw_results:
                obj_name = hit["object_name"]
                similarity = hit["similarity"]
                preview = hit.get("preview", "")

                if exclude_self and obj_name == object_name:
                    continue

                meta = self.vector_store.get_embedding_metadata(obj_name)
                extra = meta.get("metadata", {})

                keywords = [k for k in extra.get("keywords", "").split(",") if k]
                tags = [t for t in extra.get("tags", "").split(",") if t]

                result = SearchResult(
                    object_id=obj_name,
                    object_name=obj_name,
                    pool_name=extra.get("pool_name", ""),
                    relevance_score=similarity,
                    distance=1.0 - similarity,
                    content_preview=preview,
                    summary=extra.get("summary") or None,
                    keywords=keywords,
                    tags=tags,
                    content_type=extra.get("content_type", ""),
                    size_bytes=int(extra.get("size_bytes", 0)),
                )

                search_results.append(result)

                if len(search_results) >= top_k:
                    break

            logger.info(f"Found {len(search_results)} similar objects")
            return search_results

        except Exception as e:
            logger.error(f"Similar search failed: {e}")
            raise

    def search_by_keywords(
        self,
        keywords: List[str],
        top_k: int = 10,
        match_all: bool = False
    ) -> List[SearchResult]:
        """
        Search by keywords (converts to natural language query).

        Args:
            keywords: List of keywords to search for
            top_k: Number of results to return
            match_all: Unused — kept for API compatibility

        Returns:
            List of matching objects
        """
        logger.info(f"Searching by keywords: {keywords}")
        query_text = " ".join(keywords)
        return self.search(query_text=query_text, top_k=top_k)

    def get_object_details(self, object_name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about an indexed object.

        Args:
            object_name: Name of the object

        Returns:
            Dictionary with object details or None if not found
        """
        try:
            if not self.vector_store.has_embedding(object_name):
                return None

            meta = self.vector_store.get_embedding_metadata(object_name)
            embedding = self.vector_store.get_embedding(object_name)

            return {
                "object_id": object_name,
                "object_name": object_name,
                "metadata": meta,
                "has_embedding": embedding is not None,
                "embedding_dimension": len(embedding) if embedding is not None else 0,
            }

        except Exception as e:
            logger.error(f"Failed to get object details: {e}")
            return None
