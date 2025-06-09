"""
Freshness tracking and hierarchical timestamp management.

Transparent staleness calculation based on hierarchical scope changes.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import asyncpg
import redis.asyncio as redis

from config import Config
from models import (
    FreshnessCategory,
    FreshnessInfo, 
    HierarchicalTimestamp,
    ScopeLevel
)


class FreshnessManager:
    """Manages hierarchical timestamps and freshness calculations."""
    
    def __init__(self, db_pool: asyncpg.Pool, redis_client: redis.Redis):
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.freshness_config = Config.get_freshness_config()
        self.cache_config = Config.get_cache_config()
        
    async def get_freshness_info(
        self, 
        target_scope: str, 
        analysis_timestamp: datetime,
        scope_level: ScopeLevel
    ) -> FreshnessInfo:
        """Calculate freshness info for a given scope and analysis timestamp."""
        
        # Get the most recent change timestamp for this scope hierarchy
        scope_last_change = await self._get_scope_last_change(target_scope, scope_level)
        
        # Calculate staleness
        now = datetime.utcnow()
        
        # Ensure both timestamps are timezone-aware or naive
        if analysis_timestamp.tzinfo is not None:
            # analysis_timestamp is timezone-aware, make now timezone-aware too
            from datetime import timezone
            now = now.replace(tzinfo=timezone.utc)
        elif now.tzinfo is not None:
            # now is timezone-aware, make analysis_timestamp timezone-aware too
            from datetime import timezone
            analysis_timestamp = analysis_timestamp.replace(tzinfo=timezone.utc)
        
        staleness_seconds = (now - analysis_timestamp).total_seconds()
        
        # Compare analysis timestamp with scope change timestamp
        # Ensure scope_last_change has the same timezone info as analysis_timestamp
        if scope_last_change.tzinfo is None and analysis_timestamp.tzinfo is not None:
            from datetime import timezone
            scope_last_change = scope_last_change.replace(tzinfo=timezone.utc)
        elif scope_last_change.tzinfo is not None and analysis_timestamp.tzinfo is None:
            from datetime import timezone
            analysis_timestamp = analysis_timestamp.replace(tzinfo=timezone.utc)
        
        if analysis_timestamp < scope_last_change:
            # Analysis is older than the last scope change - definitely stale
            staleness_seconds = max(staleness_seconds, (now - scope_last_change).total_seconds())
        
        return FreshnessInfo(
            staleness_seconds=staleness_seconds,
            freshness_category=self._calculate_freshness_category(staleness_seconds),
            scope_last_change=scope_last_change,
            analysis_timestamp=analysis_timestamp,
            scope_path=target_scope,
            scope_level=scope_level,
            freshness_score=self._calculate_freshness_score(staleness_seconds)
        )
    
    async def update_scope_timestamp(
        self,
        scope_path: str,
        scope_level: ScopeLevel,
        change_source: Optional[str] = None,
        change_type: str = "content_modified"
    ) -> None:
        """Update timestamp for a scope and propagate to parent scopes."""
        
        timestamp = HierarchicalTimestamp(
            scope_path=scope_path,
            scope_level=scope_level,
            last_change=datetime.utcnow(),
            change_source=change_source,
            change_type=change_type
        )
        
        # Update database
        await self._store_hierarchical_timestamp(timestamp)
        
        # Invalidate cache for this scope and parent scopes
        await self._invalidate_scope_cache(scope_path)
        
        # Propagate timestamp update to parent scopes
        await self._propagate_timestamp_update(scope_path, timestamp.last_change)
    
    async def _get_scope_last_change(
        self, 
        target_scope: str, 
        scope_level: ScopeLevel
    ) -> datetime:
        """Get the most recent change timestamp for scope hierarchy."""
        
        # Try cache first
        cache_key = f"scope_timestamp:{target_scope}"
        cached_timestamp = await self.redis_client.get(cache_key)
        
        if cached_timestamp:
            return datetime.fromisoformat(cached_timestamp.decode())
        
        # Query database for hierarchical timestamps
        async with self.db_pool.acquire() as conn:
            # Get all scope levels that could affect this scope
            scope_patterns = self._get_scope_patterns(target_scope)
            
            query = """
                SELECT MAX(last_change) as last_change
                FROM hierarchical_timestamps 
                WHERE scope_path = ANY($1::text[])
                   OR $2 LIKE scope_path || '.%'
            """
            
            result = await conn.fetchrow(query, scope_patterns, target_scope)
            
            if result and result['last_change']:
                last_change = result['last_change']
            else:
                # No changes recorded - use epoch as default
                last_change = datetime(1970, 1, 1)
            
            # Cache the result
            await self.redis_client.setex(
                cache_key, 
                self.cache_config['ttl_seconds'], 
                last_change.isoformat()
            )
            
            return last_change
    
    def _calculate_freshness_category(self, staleness_seconds: float) -> FreshnessCategory:
        """Calculate freshness category based on staleness."""
        
        if staleness_seconds <= self.freshness_config['fresh_threshold']:
            return FreshnessCategory.FRESH
        elif staleness_seconds <= self.freshness_config['recent_threshold']:
            return FreshnessCategory.RECENT
        elif staleness_seconds <= self.freshness_config['stale_threshold']:
            return FreshnessCategory.STALE
        else:
            return FreshnessCategory.EXPIRED
    
    def _calculate_freshness_score(self, staleness_seconds: float) -> float:
        """Calculate freshness score from staleness seconds."""
        
        # Exponential decay: 1.0 at 0 seconds, 0.5 at 1 hour, 0.1 at 1 day
        if staleness_seconds <= 0:
            return 1.0
        
        # Use exponential decay with 1-hour half-life
        import math
        half_life_seconds = 3600  # 1 hour
        score = math.exp(-0.693 * staleness_seconds / half_life_seconds)
        
        return max(0.0, min(1.0, score))
    
    def _get_scope_patterns(self, target_scope: str) -> List[str]:
        """Get all scope patterns that could affect the target scope."""
        
        patterns = []
        parts = target_scope.split('.')
        
        # Add progressively more specific scopes
        for i in range(len(parts)):
            scope_part = '.'.join(parts[:i+1])
            patterns.append(scope_part)
        
        return patterns
    
    async def _store_hierarchical_timestamp(self, timestamp: HierarchicalTimestamp) -> None:
        """Store hierarchical timestamp in database."""
        
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO hierarchical_timestamps 
                (scope_path, scope_level, last_change, change_source, change_type)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (scope_path, scope_level) 
                DO UPDATE SET 
                    last_change = EXCLUDED.last_change,
                    change_source = EXCLUDED.change_source,
                    change_type = EXCLUDED.change_type
            """, 
                timestamp.scope_path,
                timestamp.scope_level.value,
                timestamp.last_change,
                timestamp.change_source,
                timestamp.change_type
            )
    
    async def _invalidate_scope_cache(self, scope_path: str) -> None:
        """Invalidate cache entries for scope and parent scopes."""
        
        cache_patterns = self._get_scope_patterns(scope_path)
        cache_keys = [f"scope_timestamp:{pattern}" for pattern in cache_patterns]
        
        if cache_keys:
            await self.redis_client.delete(*cache_keys)
    
    async def _propagate_timestamp_update(
        self, 
        scope_path: str, 
        change_timestamp: datetime
    ) -> None:
        """Propagate timestamp update to parent scopes."""
        
        parts = scope_path.split('.')
        
        # Update each parent scope level
        for i in range(len(parts) - 1):
            parent_scope = '.'.join(parts[:i+1])
            parent_level = self._get_scope_level_from_depth(i)
            
            # Only update if this change is more recent
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO hierarchical_timestamps 
                    (scope_path, scope_level, last_change, change_source, change_type)
                    VALUES ($1, $2, $3, $4, 'propagated_change')
                    ON CONFLICT (scope_path, scope_level) 
                    DO UPDATE SET 
                        last_change = GREATEST(hierarchical_timestamps.last_change, EXCLUDED.last_change),
                        change_source = CASE 
                            WHEN EXCLUDED.last_change > hierarchical_timestamps.last_change 
                            THEN EXCLUDED.change_source
                            ELSE hierarchical_timestamps.change_source
                        END
                """, 
                    parent_scope,
                    parent_level.value,
                    change_timestamp,
                    f"child_change:{scope_path}"
                )
    
    def _get_scope_level_from_depth(self, depth: int) -> ScopeLevel:
        """Get scope level based on hierarchy depth."""
        
        if depth == 0:
            return ScopeLevel.PROJECT
        elif depth == 1:
            return ScopeLevel.DOMAIN
        elif depth == 2:
            return ScopeLevel.MODULE
        else:
            return ScopeLevel.FILE
    
    async def get_stale_scopes(
        self, 
        staleness_threshold_hours: int = 24,
        limit: int = 100
    ) -> List[Tuple[str, datetime, float]]:
        """Get scopes that haven't been updated recently."""
        
        threshold_time = datetime.utcnow() - timedelta(hours=staleness_threshold_hours)
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT 
                    ar.target_scope,
                    ar.analysis_timestamp,
                    EXTRACT(EPOCH FROM (NOW() - ar.analysis_timestamp)) as staleness_seconds
                FROM analysis_results ar
                LEFT JOIN hierarchical_timestamps ht ON ar.target_scope = ht.scope_path
                WHERE ar.analysis_timestamp < $1
                   OR ht.last_change > ar.analysis_timestamp
                ORDER BY staleness_seconds DESC
                LIMIT $2
            """, threshold_time, limit)
            
            return [
                (row['target_scope'], row['analysis_timestamp'], row['staleness_seconds'])
                for row in rows
            ]
    
    async def bulk_update_staleness(
        self, 
        scope_changes: List[Tuple[str, datetime]]
    ) -> int:
        """Bulk update staleness for multiple scopes."""
        
        updated_count = 0
        
        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                for scope_path, change_time in scope_changes:
                    # Determine scope level from path depth
                    scope_level = self._get_scope_level_from_depth(len(scope_path.split('.')) - 1)
                    
                    await conn.execute("""
                        INSERT INTO hierarchical_timestamps 
                        (scope_path, scope_level, last_change, change_source, change_type)
                        VALUES ($1, $2, $3, 'bulk_update', 'staleness_update')
                        ON CONFLICT (scope_path, scope_level) 
                        DO UPDATE SET 
                            last_change = GREATEST(hierarchical_timestamps.last_change, EXCLUDED.last_change)
                    """, scope_path, scope_level.value, change_time)
                    
                    updated_count += 1
        
        # Clear related cache entries
        cache_keys = [f"scope_timestamp:{scope}" for scope, _ in scope_changes]
        if cache_keys:
            await self.redis_client.delete(*cache_keys)
        
        return updated_count 