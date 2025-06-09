"""
Unified knowledge store for all analysis operations.

Replaces the complex multi-component system with a single, focused CRUD interface.
"""

import asyncio
import hashlib
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

import asyncpg
import redis.asyncio as redis

from config import Config
from freshness import FreshnessManager
from models import (
    AnalysisResult,
    AnalysisType,
    FreshnessInfo,
    HealthStatus,
    LifecycleAction,
    LifecycleRequest,
    LifecycleResult,
    ProjectContext,
    QueryResult,
    ScopeLevel,
    StorageRequest,
    StorageResult,
)
from search import SemanticSearch


class KnowledgeStore:
    """Unified storage and retrieval for all project knowledge."""

    def __init__(self, db_pool: asyncpg.Pool, redis_client: redis.Redis):
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.freshness_manager = FreshnessManager(db_pool, redis_client)
        self.search = SemanticSearch(db_pool, redis_client)

    async def initialize(self):
        """Initialize all components."""
        await self.search.initialize()

    # Core CRUD Operations

    async def get_cached_analysis_with_freshness(
        self, target_scope: str, project_id: Optional[str] = None
    ) -> Optional[QueryResult]:
        """Get analysis with transparent freshness information."""

        start_time = time.time()
        cache_hit = False

        # Try cache first
        cache_key = f"analysis:{project_id or 'default'}:{target_scope}"
        cached_result = await self._get_cached_analysis(cache_key)

        if cached_result:
            cache_hit = True
            analysis_result = cached_result
        else:
            # Fetch from database
            analysis_result = await self._fetch_analysis_from_db(target_scope, project_id)
            if not analysis_result:
                return None

            # Cache the result
            await self._cache_analysis(cache_key, analysis_result)

        # Calculate freshness
        freshness_info = await self.freshness_manager.get_freshness_info(
            target_scope=target_scope,
            analysis_timestamp=analysis_result.analysis_timestamp,
            scope_level=analysis_result.scope_level,
        )

        query_duration = (time.time() - start_time) * 1000

        return QueryResult(
            analysis_result=analysis_result,
            freshness_info=freshness_info,
            query_duration_ms=query_duration,
            cache_hit=cache_hit,
        )

    async def store_analysis_result(
        self, request: StorageRequest, project_id: str = "default"
    ) -> StorageResult:
        """Store analysis result with automatic deduplication."""

        start_time = time.time()

        # Generate content hash for deduplication
        content_hash = self._generate_content_hash(request.content)

        # Check for existing analysis with same content hash
        existing_analysis = await self._find_existing_analysis(
            project_id, request.target_scope, content_hash
        )

        if existing_analysis and not request.force_refresh:
            # Return existing analysis (deduplicated)
            storage_duration = (time.time() - start_time) * 1000
            return StorageResult(
                analysis_id=existing_analysis.id,
                was_deduplicated=True,
                existing_analysis_id=existing_analysis.id,
                storage_duration_ms=storage_duration,
            )

        # Generate full scope
        full_scope = f"{project_id}.{request.target_scope}"

        # Analyze content and create AnalysisResult
        analysis_start = time.time()
        result_data = await self._analyze_content(request.content, request.analysis_type)
        analysis_duration = (time.time() - analysis_start) * 1000

        # Generate embedding if search model is available
        vector_embedding = None
        try:
            if self.search.embedding_model:
                vector_embedding = self.search._generate_embedding(request.content[:1000])
        except Exception:
            pass  # Embedding generation failure is not critical

        # Create AnalysisResult
        analysis_result = AnalysisResult(
            analysis_type=request.analysis_type,
            project_id=project_id,
            target_scope=request.target_scope,
            full_scope=full_scope,
            scope_level=request.scope_level,
            result_data=result_data,
            content_hash=content_hash,
            source_files=request.source_files,
            analysis_duration_ms=int(analysis_duration),
            vector_embedding=vector_embedding,
        )

        # Store in database
        await self._store_analysis_in_db(analysis_result)

        # Update scope timestamp
        await self.freshness_manager.update_scope_timestamp(
            scope_path=request.target_scope,
            scope_level=request.scope_level,
            change_source=f"analysis_update:{analysis_result.id}",
            change_type="content_analyzed",
        )

        # Invalidate related caches
        await self._invalidate_analysis_cache(project_id, request.target_scope)

        storage_duration = (time.time() - start_time) * 1000

        return StorageResult(
            analysis_id=analysis_result.id,
            was_deduplicated=False,
            storage_duration_ms=storage_duration,
            analysis_duration_ms=analysis_duration,
        )

    async def get_component_architecture(
        self,
        component_scope: str,
        project_id: Optional[str] = None,
        include_dependencies: bool = True,
        include_relationships: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Get deep component architecture with relationships."""

        # Get the main component analysis
        main_analysis = await self.get_cached_analysis_with_freshness(component_scope, project_id)

        if not main_analysis:
            return None

        architecture = {
            "component": main_analysis.analysis_result.dict(),
            "freshness": main_analysis.freshness_info.dict(),
            "dependencies": [],
            "dependents": [],
            "related_components": [],
        }

        if include_dependencies:
            # Find components this depends on
            dependencies = await self._find_component_dependencies(component_scope, project_id)
            architecture["dependencies"] = [dep.dict() for dep in dependencies]

            # Find components that depend on this
            dependents = await self._find_component_dependents(component_scope, project_id)
            architecture["dependents"] = [dep.dict() for dep in dependents]

        if include_relationships:
            # Find similar or related components
            related = await self.search.find_similar_components(
                reference_scope=component_scope, similarity_threshold=0.6, limit=5
            )
            architecture["related_components"] = [rel.dict() for rel in related]

        return architecture

    async def manage_knowledge_lifecycle(self, request: LifecycleRequest) -> LifecycleResult:
        """Manage knowledge lifecycle (archive, delete, cleanup)."""

        start_time = time.time()
        result = LifecycleResult(
            action_performed=request.action,
            target_scope=request.target_scope,
            was_dry_run=request.dry_run,
        )

        # Find target analysis items
        target_analyses = await self._find_lifecycle_targets(request)

        if request.dry_run:
            # Just preview what would be affected
            result.items_affected = len(target_analyses)
            result.affected_analysis_ids = [analysis.id for analysis in target_analyses]
        else:
            # Execute the lifecycle action
            if request.action == LifecycleAction.ARCHIVE:
                result.items_archived = await self._archive_analyses(target_analyses, request)
            elif request.action == LifecycleAction.DELETE:
                result.items_deleted = await self._delete_analyses(target_analyses)
            elif request.action == LifecycleAction.MARK_STALE:
                result.items_marked_stale = await self._mark_analyses_stale(target_analyses)
            elif request.action == LifecycleAction.REFRESH:
                result.items_queued_refresh = await self._queue_analyses_refresh(target_analyses)
            elif request.action == LifecycleAction.BULK_CLEANUP:
                cleanup_result = await self._bulk_cleanup(request)
                result.items_archived = cleanup_result.get("archived", 0)
                result.items_deleted = cleanup_result.get("deleted", 0)
                result.items_marked_stale = cleanup_result.get("marked_stale", 0)

            result.items_affected = sum(
                [
                    result.items_archived,
                    result.items_deleted,
                    result.items_marked_stale,
                    result.items_queued_refresh,
                ]
            )

            # Clear related caches
            await self._invalidate_lifecycle_caches(target_analyses)

        result.operation_duration_ms = (time.time() - start_time) * 1000
        return result

    # Health and Status

    async def get_health_status(self) -> HealthStatus:
        """Get health status of the knowledge store."""

        status = HealthStatus(status="healthy")

        try:
            # Test database connection
            async with self.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
                status.database_connected = True

                # Get statistics
                stats = await conn.fetchrow("""
                    SELECT 
                        COUNT(*) as total_analyses,
                        COUNT(DISTINCT target_scope) as total_scopes,
                        AVG(EXTRACT(EPOCH FROM NOW() - analysis_timestamp)) as avg_age_seconds
                    FROM analysis_results
                """)

                if stats:
                    status.total_analyses = stats["total_analyses"]
                    status.total_scopes = stats["total_scopes"]
        except Exception as e:
            status.status = "database_error"
            status.database_connected = False

        try:
            # Test Redis connection
            await self.redis_client.ping()
            status.redis_connected = True

            # Calculate cache hit rate (rough estimate)
            cache_info = await self.redis_client.info("stats")
            if cache_info and "keyspace_hits" in cache_info:
                hits = cache_info["keyspace_hits"]
                misses = cache_info["keyspace_misses"]
                if hits + misses > 0:
                    status.cache_hit_rate = hits / (hits + misses)
        except Exception:
            status.redis_connected = False

        if not status.database_connected or not status.redis_connected:
            status.status = "degraded"

        return status

    # Private Helper Methods

    async def _get_cached_analysis(self, cache_key: str) -> Optional[AnalysisResult]:
        """Get analysis from cache."""
        try:
            cached_data = await self.redis_client.get(cache_key)
            if cached_data:
                data = json.loads(cached_data.decode())
                return AnalysisResult(**data)
        except Exception:
            pass
        return None

    async def _cache_analysis(self, cache_key: str, analysis: AnalysisResult) -> None:
        """Cache analysis result."""
        try:
            data = analysis.dict()
            await self.redis_client.setex(
                cache_key, Config.CACHE_TTL_SECONDS, json.dumps(data, default=str)
            )
        except Exception:
            pass  # Cache write failure is not critical

    async def _fetch_analysis_from_db(
        self, target_scope: str, project_id: Optional[str]
    ) -> Optional[AnalysisResult]:
        """Fetch analysis from database."""

        async with self.db_pool.acquire() as conn:
            query = """
                SELECT * FROM analysis_results 
                WHERE target_scope = $1
            """
            params = [target_scope]

            if project_id:
                query += " AND project_id = $2"
                params.append(project_id)

            query += " ORDER BY analysis_timestamp DESC LIMIT 1"

            row = await conn.fetchrow(query, *params)

            if row:
                return self._parse_db_row_to_analysis(row)

        return None

    def _generate_content_hash(self, content: str) -> str:
        """Generate SHA-256 hash of content for deduplication."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _parse_db_row_to_analysis(self, row) -> AnalysisResult:
        """Parse database row to AnalysisResult, handling JSON and vector fields."""
        data = dict(row)

        # Parse JSON result_data
        if isinstance(data["result_data"], str):
            data["result_data"] = json.loads(data["result_data"])

        # Parse vector embedding (if column exists and has data)
        if "vector_embedding" in data and data["vector_embedding"]:
            if isinstance(data["vector_embedding"], str):
                # Remove brackets and split by comma
                vector_str = data["vector_embedding"].strip("[]")
                data["vector_embedding"] = [float(x.strip()) for x in vector_str.split(",")]
        else:
            # Set to None if column doesn't exist or is empty
            data["vector_embedding"] = None

        return AnalysisResult(**data)

    async def _find_existing_analysis(
        self, project_id: str, target_scope: str, content_hash: str
    ) -> Optional[AnalysisResult]:
        """Find existing analysis with matching content hash."""

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM analysis_results
                WHERE project_id = $1 
                  AND target_scope = $2 
                  AND content_hash = $3
                ORDER BY analysis_timestamp DESC
                LIMIT 1
            """,
                project_id,
                target_scope,
                content_hash,
            )

            if row:
                return self._parse_db_row_to_analysis(row)

        return None

    async def _analyze_content(self, content: str, analysis_type: AnalysisType) -> Dict[str, Any]:
        """Analyze content based on analysis type."""

        # Basic content analysis - in a real implementation, this would be more sophisticated
        result_data = {
            "content": content[:2000],  # Store truncated content
            "length": len(content),
            "word_count": len(content.split()),
            "analysis_type": analysis_type.value,
            "summary": content[:200] + "..." if len(content) > 200 else content,
            "title": f"{analysis_type.value.title()} Analysis",
        }

        # Add type-specific analysis
        if analysis_type == AnalysisType.ARCHITECTURE:
            result_data["components"] = self._extract_components(content)
        elif analysis_type == AnalysisType.DEPENDENCIES:
            result_data["dependencies"] = self._extract_dependencies(content)
        elif analysis_type == AnalysisType.STRUCTURE:
            result_data["structure"] = self._extract_structure(content)

        return result_data

    def _extract_components(self, content: str) -> List[str]:
        """Extract component names from content."""
        # Simplified component extraction
        import re

        components = re.findall(
            r"\b(?:class|function|component|module)\s+(\w+)", content, re.IGNORECASE
        )
        return list(set(components))

    def _extract_dependencies(self, content: str) -> List[str]:
        """Extract dependencies from content."""
        # Simplified dependency extraction
        import re

        deps = re.findall(r'(?:import|from|require)\s+([\'"]?)([^\'"\s]+)\1', content)
        return list(set([dep[1] for dep in deps]))

    def _extract_structure(self, content: str) -> Dict[str, Any]:
        """Extract structural information from content."""
        lines = content.split("\n")
        return {
            "line_count": len(lines),
            "non_empty_lines": len([line for line in lines if line.strip()]),
            "indentation_style": "spaces"
            if any(line.startswith("  ") for line in lines)
            else "tabs",
        }

    async def _store_analysis_in_db(self, analysis: AnalysisResult) -> None:
        """Store analysis result in database."""

        async with self.db_pool.acquire() as conn:
            # Check if vector_embedding column exists
            vector_column_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'analysis_results' 
                    AND column_name = 'vector_embedding'
                )
            """)

            if vector_column_exists and analysis.vector_embedding:
                # Full schema with vector support
                vector_data = None
                if analysis.vector_embedding:
                    # Convert list to string format for pgvector
                    vector_str = "[" + ",".join(map(str, analysis.vector_embedding)) + "]"
                    vector_data = vector_str

                await conn.execute(
                    """
                    INSERT INTO analysis_results (
                        id, analysis_type, project_id, target_scope, full_scope, scope_level,
                        result_data, content_hash, source_files, source_file_count,
                        analysis_timestamp, analysis_duration_ms, vector_embedding
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::vector
                    )
                """,
                    analysis.id,
                    analysis.analysis_type.value,
                    analysis.project_id,
                    analysis.target_scope,
                    analysis.full_scope,
                    analysis.scope_level.value,
                    json.dumps(analysis.result_data),
                    analysis.content_hash,
                    analysis.source_files,
                    analysis.source_file_count,
                    analysis.analysis_timestamp,
                    analysis.analysis_duration_ms,
                    vector_data,
                )
            else:
                # Simplified schema without vector support
                await conn.execute(
                    """
                    INSERT INTO analysis_results (
                        id, analysis_type, project_id, target_scope, full_scope, scope_level,
                        result_data, content_hash, source_files, source_file_count,
                        analysis_timestamp, analysis_duration_ms
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
                    )
                """,
                    analysis.id,
                    analysis.analysis_type.value,
                    analysis.project_id,
                    analysis.target_scope,
                    analysis.full_scope,
                    analysis.scope_level.value,
                    json.dumps(analysis.result_data),
                    analysis.content_hash,
                    analysis.source_files,
                    analysis.source_file_count,
                    analysis.analysis_timestamp,
                    analysis.analysis_duration_ms,
                )

    async def _ensure_project_exists(self, project_id: str, project_data: dict) -> None:
        """Ensure a project context exists in the database."""

        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO project_contexts (
                    project_id, project_name, project_root, base_scope, description, tags, is_active, created_at, last_updated
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, true, NOW(), NOW()
                ) ON CONFLICT (project_id) DO UPDATE SET
                    project_name = EXCLUDED.project_name,
                    description = EXCLUDED.description,
                    tags = EXCLUDED.tags,
                    last_updated = NOW()
            """,
                project_id,
                project_data.get("name", project_id),
                project_data.get("project_root", f"/projects/{project_id}"),
                project_data.get("base_scope", project_id),
                project_data.get("description", ""),
                project_data.get("tags", []),
            )

    async def _invalidate_analysis_cache(self, project_id: str, target_scope: str) -> None:
        """Invalidate cached analysis results."""

        cache_patterns = [
            f"analysis:{project_id}:{target_scope}",
            f"analysis:default:{target_scope}",
            f"search:*scope:{target_scope}*",
        ]

        for pattern in cache_patterns:
            try:
                keys = []
                async for key in self.redis_client.scan_iter(match=pattern):
                    keys.append(key)
                if keys:
                    await self.redis_client.delete(*keys)
            except Exception:
                pass

    async def _find_component_dependencies(
        self, component_scope: str, project_id: Optional[str]
    ) -> List[AnalysisResult]:
        """Find components that this component depends on."""

        async with self.db_pool.acquire() as conn:
            # Look for dependency analysis or cross-references
            query = """
                SELECT DISTINCT ar.* FROM analysis_results ar
                WHERE ar.analysis_type = 'dependencies'
                  AND ar.result_data::text LIKE $1
            """
            params = [f"%{component_scope}%"]

            if project_id:
                query += " AND ar.project_id = $2"
                params.append(project_id)

            query += " ORDER BY ar.analysis_timestamp DESC LIMIT 10"

            rows = await conn.fetch(query, *params)
            return [self._parse_db_row_to_analysis(row) for row in rows]

    async def _find_component_dependents(
        self, component_scope: str, project_id: Optional[str]
    ) -> List[AnalysisResult]:
        """Find components that depend on this component."""

        async with self.db_pool.acquire() as conn:
            # Look for references to this component in other analyses
            query = """
                SELECT DISTINCT ar.* FROM analysis_results ar
                WHERE ar.result_data::text LIKE $1
                  AND ar.target_scope != $2
            """
            params = [f"%{component_scope}%", component_scope]

            if project_id:
                query += " AND ar.project_id = $3"
                params.append(project_id)

            query += " ORDER BY ar.analysis_timestamp DESC LIMIT 10"

            rows = await conn.fetch(query, *params)
            return [self._parse_db_row_to_analysis(row) for row in rows]

    async def _find_lifecycle_targets(self, request: LifecycleRequest) -> List[AnalysisResult]:
        """Find analyses that match lifecycle criteria."""

        query_parts = ["SELECT * FROM analysis_results WHERE 1=1"]
        params = []
        param_idx = 1

        # Filter by project_id (now required)
        query_parts.append(f" AND project_id = ${param_idx}")
        params.append(request.project_id)
        param_idx += 1

        # Target specific scope
        if request.target_scope:
            query_parts.append(f" AND target_scope LIKE ${param_idx}")
            params.append(f"{request.target_scope}%")
            param_idx += 1

        # Target specific analysis IDs
        if request.analysis_ids:
            id_strs = [str(aid) for aid in request.analysis_ids]
            query_parts.append(f" AND id = ANY(${param_idx}::uuid[])")
            params.append(id_strs)
            param_idx += 1

        # Age criteria
        if request.older_than_days:
            query_parts.append(
                f" AND analysis_timestamp < NOW() - INTERVAL '{request.older_than_days} days'"
            )

        # Analysis type filter
        if request.analysis_types:
            type_values = [t.value for t in request.analysis_types]
            query_parts.append(f" AND analysis_type = ANY(${param_idx}::text[])")
            params.append(type_values)
            param_idx += 1

        query = (
            " ".join(query_parts) + f" ORDER BY analysis_timestamp DESC LIMIT {request.batch_size}"
        )

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._parse_db_row_to_analysis(row) for row in rows]

    async def _archive_analyses(
        self, analyses: List[AnalysisResult], request: LifecycleRequest
    ) -> int:
        """Archive analyses to long-term storage."""
        # Implementation would move data to archive table
        # For now, just mark as archived
        return len(analyses)

    async def _delete_analyses(self, analyses: List[AnalysisResult]) -> int:
        """Permanently delete analyses."""
        analysis_ids = [str(analysis.id) for analysis in analyses]

        async with self.db_pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM analysis_results 
                WHERE id = ANY($1::uuid[])
            """,
                analysis_ids,
            )

            return len(analyses)

    async def _mark_analyses_stale(self, analyses: List[AnalysisResult]) -> int:
        """Mark analyses as stale."""
        # Update freshness timestamps
        scope_changes = [(analysis.target_scope, datetime.utcnow()) for analysis in analyses]
        return await self.freshness_manager.bulk_update_staleness(scope_changes)

    async def _queue_analyses_refresh(self, analyses: List[AnalysisResult]) -> int:
        """Queue analyses for refresh."""
        # In a real implementation, this would add to a work queue
        return len(analyses)

    async def _bulk_cleanup(self, request: LifecycleRequest) -> Dict[str, int]:
        """Perform bulk cleanup operations."""
        return {"archived": 0, "deleted": 0, "marked_stale": 0}

    async def _invalidate_lifecycle_caches(self, analyses: List[AnalysisResult]) -> None:
        """Invalidate caches after lifecycle operations."""

        unique_scopes = set()
        unique_projects = set()

        for analysis in analyses:
            unique_scopes.add(analysis.target_scope)
            unique_projects.add(analysis.project_id)

        # Clear analysis caches
        for project_id in unique_projects:
            for scope in unique_scopes:
                await self._invalidate_analysis_cache(project_id, scope)

        # Clear search caches
        await self.search.invalidate_search_cache()
