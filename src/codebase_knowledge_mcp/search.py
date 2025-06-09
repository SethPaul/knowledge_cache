"""
Semantic search implementation with pgvector.

High-performance vector search for project knowledge with hierarchical scope filtering.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import asyncpg
import numpy as np
import redis.asyncio as redis
from sentence_transformers import SentenceTransformer

from config import Config
from models import AnalysisType, ScopeLevel, SearchResult


class SemanticSearch:
    """Semantic search using sentence transformers and pgvector."""

    def __init__(self, db_pool: asyncpg.Pool, redis_client: redis.Redis):
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.embedding_model = None
        self._model_loading = False

    async def initialize(self):
        """Initialize the embedding model."""
        if self.embedding_model is None and not self._model_loading:
            self._model_loading = True
            try:
                self.embedding_model = SentenceTransformer(Config.EMBEDDING_MODEL)
            finally:
                self._model_loading = False

    async def search_project_knowledge(
        self,
        query: str,
        project_id: str,  # Now required
        scope_filter: Optional[str] = None,
        analysis_types: Optional[List[AnalysisType]] = None,
        limit: int = None,
        similarity_threshold: float = 0.5,
    ) -> List[SearchResult]:
        """Semantic search across project knowledge."""

        start_time = time.time()

        # Ensure model is loaded
        await self.initialize()

        # Set default limit
        if limit is None:
            limit = Config.SEARCH_DEFAULT_LIMIT
        limit = min(limit, Config.SEARCH_MAX_LIMIT)

        # Check cache first
        cache_key = self._generate_cache_key(
            query, project_id, scope_filter, analysis_types, limit, similarity_threshold
        )

        cached_results = await self._get_cached_results(cache_key)
        if cached_results:
            return cached_results

        # Generate query embedding
        query_embedding = self._generate_embedding(query)

        # Build search query
        sql_query, params = self._build_search_query(
            query_embedding, project_id, scope_filter, analysis_types, limit, similarity_threshold
        )

        # Execute search
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(sql_query, *params)

        # Convert to SearchResult objects
        results = []
        for row in rows:
            result = SearchResult(
                content_chunk=row["content_chunk"],
                title=row.get("title", ""),
                scope=row["target_scope"],
                similarity_score=float(row["similarity_score"]),
                analysis_type=AnalysisType(row["analysis_type"]),
                source_file=row.get("source_file"),
                last_modified=row.get("analysis_timestamp"),
                content_hash=row.get("content_hash"),
            )
            results.append(result)

        # Cache results
        await self._cache_results(cache_key, results)

        query_duration = (time.time() - start_time) * 1000

        # Log performance metrics
        if Config.INCLUDE_PERFORMANCE_METRICS:
            print(f"Search completed in {query_duration:.1f}ms, {len(results)} results")

        return results

    async def search_by_scope_hierarchy(
        self,
        target_scope: str,
        include_children: bool = True,
        include_parents: bool = False,
        limit: int = None,
    ) -> List[SearchResult]:
        """Search within a specific scope hierarchy."""

        if limit is None:
            limit = Config.SEARCH_DEFAULT_LIMIT

        # Build scope patterns for hierarchical search
        scope_patterns = self._build_scope_patterns(target_scope, include_children, include_parents)

        async with self.db_pool.acquire() as conn:
            # Use scope pattern matching instead of vector search
            query = """
                SELECT 
                    COALESCE(
                        LEFT(result_data->>'content', 500),
                        LEFT(result_data->>'summary', 500),
                        'No content preview available'
                    ) as content_chunk,
                    COALESCE(result_data->>'title', target_scope) as title,
                    target_scope,
                    1.0 as similarity_score,  -- Perfect match for scope-based search
                    analysis_type,
                    array_to_string(source_files, ', ') as source_file,
                    analysis_timestamp,
                    content_hash
                FROM analysis_results
                WHERE target_scope = ANY($1::text[])
                   OR ($2 = true AND target_scope LIKE $3 || '.%')
                   OR ($4 = true AND $3 LIKE target_scope || '.%')
                ORDER BY analysis_timestamp DESC
                LIMIT $5
            """

            rows = await conn.fetch(
                query, scope_patterns, include_children, target_scope, include_parents, limit
            )

        results = []
        for row in rows:
            result = SearchResult(
                content_chunk=row["content_chunk"],
                title=row["title"],
                scope=row["target_scope"],
                similarity_score=float(row["similarity_score"]),
                analysis_type=AnalysisType(row["analysis_type"]),
                source_file=row["source_file"],
                last_modified=row["analysis_timestamp"],
                content_hash=row["content_hash"],
            )
            results.append(result)

        return results

    async def find_similar_components(
        self, reference_scope: str, similarity_threshold: float = 0.7, limit: int = 10
    ) -> List[SearchResult]:
        """Find components similar to a reference component."""

        # Get the reference component's embedding
        async with self.db_pool.acquire() as conn:
            ref_row = await conn.fetchrow(
                """
                SELECT vector_embedding, result_data
                FROM analysis_results 
                WHERE target_scope = $1
                  AND vector_embedding IS NOT NULL
                ORDER BY analysis_timestamp DESC
                LIMIT 1
            """,
                reference_scope,
            )

            if not ref_row or not ref_row["vector_embedding"]:
                return []

            # Search for similar embeddings
            ref_embedding = ref_row["vector_embedding"]

            # Convert embedding to string format for pgvector if it's a list
            if isinstance(ref_embedding, list):
                ref_embedding = "[" + ",".join(map(str, ref_embedding)) + "]"

            query = """
                SELECT 
                    COALESCE(
                        LEFT(result_data->>'content', 500),
                        LEFT(result_data->>'summary', 500),
                        'No content preview available'
                    ) as content_chunk,
                    COALESCE(result_data->>'title', target_scope) as title,
                    target_scope,
                    1 - (vector_embedding <=> $1::vector) as similarity_score,
                    analysis_type,
                    array_to_string(source_files, ', ') as source_file,
                    analysis_timestamp,
                    content_hash
                FROM analysis_results
                WHERE target_scope != $2
                  AND vector_embedding IS NOT NULL
                  AND 1 - (vector_embedding <=> $1::vector) >= $3
                ORDER BY vector_embedding <=> $1::vector
                LIMIT $4
            """

            rows = await conn.fetch(
                query, ref_embedding, reference_scope, similarity_threshold, limit
            )

        results = []
        for row in rows:
            result = SearchResult(
                content_chunk=row["content_chunk"],
                title=row["title"],
                scope=row["target_scope"],
                similarity_score=float(row["similarity_score"]),
                analysis_type=AnalysisType(row["analysis_type"]),
                source_file=row["source_file"],
                last_modified=row["analysis_timestamp"],
                content_hash=row["content_hash"],
            )
            results.append(result)

        return results

    def _generate_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for text."""

        if self.embedding_model is None:
            raise RuntimeError("Embedding model not initialized")

        # Generate embedding
        embedding = self.embedding_model.encode(text, normalize_embeddings=True)

        # Convert to list for JSON serialization
        return embedding.tolist()

    def _build_search_query(
        self,
        query_embedding: List[float],
        project_id: str,  # Now required
        scope_filter: Optional[str],
        analysis_types: Optional[List[AnalysisType]],
        limit: int,
        similarity_threshold: float,
    ) -> Tuple[str, List[Any]]:
        """Build parameterized SQL query for vector search."""

        base_query = """
            SELECT 
                COALESCE(
                    LEFT(result_data->>'content', 500),
                    LEFT(result_data->>'summary', 500),
                    'No content preview available'
                ) as content_chunk,
                COALESCE(result_data->>'title', target_scope) as title,
                target_scope,
                1 - (vector_embedding <=> $1::vector) as similarity_score,
                analysis_type,
                array_to_string(source_files, ', ') as source_file,
                analysis_timestamp,
                content_hash
            FROM analysis_results
            WHERE vector_embedding IS NOT NULL
              AND 1 - (vector_embedding <=> $1::vector) >= $2
        """

        # Convert embedding to string format for pgvector
        embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
        params = [embedding_str, similarity_threshold]
        param_idx = 3

        # Add project filter (now required)
        base_query += f" AND project_id = ${param_idx}"
        params.append(project_id)
        param_idx += 1

        # Add scope filter
        if scope_filter:
            base_query += f" AND target_scope LIKE ${param_idx}"
            params.append(f"{scope_filter}%")
            param_idx += 1

        # Add analysis type filter
        if analysis_types:
            type_values = [t.value for t in analysis_types]
            base_query += f" AND analysis_type = ANY(${param_idx}::text[])"
            params.append(type_values)
            param_idx += 1

        # Add ordering and limit
        base_query += f"""
            ORDER BY vector_embedding <=> $1::vector
            LIMIT ${param_idx}
        """
        params.append(limit)

        return base_query, params

    def _build_scope_patterns(
        self, target_scope: str, include_children: bool, include_parents: bool
    ) -> List[str]:
        """Build scope patterns for hierarchical matching."""

        patterns = [target_scope]

        if include_children:
            patterns.append(f"{target_scope}.%")

        if include_parents:
            parts = target_scope.split(".")
            for i in range(len(parts) - 1):
                parent_scope = ".".join(parts[: i + 1])
                patterns.append(parent_scope)

        return patterns

    def _generate_cache_key(
        self,
        query: str,
        project_id: str,  # Now required
        scope_filter: Optional[str],
        analysis_types: Optional[List[AnalysisType]],
        limit: int,
        similarity_threshold: float,
    ) -> str:
        """Generate cache key for search parameters."""

        # Create deterministic key from parameters
        key_parts = [
            f"query:{hash(query)}",
            f"project:{project_id}",  # Now always present
            f"scope:{scope_filter or 'all'}",
            f"types:{','.join(t.value for t in (analysis_types or []))}",
            f"limit:{limit}",
            f"threshold:{similarity_threshold}",
        ]

        return f"search:{'|'.join(key_parts)}"

    async def _get_cached_results(self, cache_key: str) -> Optional[List[SearchResult]]:
        """Get cached search results."""

        try:
            cached_data = await self.redis_client.get(cache_key)
            if cached_data:
                import json

                data = json.loads(cached_data.decode())
                return [SearchResult(**item) for item in data]
        except Exception:
            # Cache miss or error - proceed with fresh search
            pass

        return None

    async def _cache_results(self, cache_key: str, results: List[SearchResult]) -> None:
        """Cache search results."""

        try:
            import json

            data = [result.dict() for result in results]
            await self.redis_client.setex(
                cache_key, Config.CACHE_TTL_SECONDS, json.dumps(data, default=str)
            )
        except Exception:
            # Cache write failure - not critical
            pass

    async def invalidate_search_cache(self, pattern: str = "search:*") -> int:
        """Invalidate cached search results."""

        try:
            keys = []
            async for key in self.redis_client.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                return await self.redis_client.delete(*keys)
            return 0
        except Exception:
            return 0
