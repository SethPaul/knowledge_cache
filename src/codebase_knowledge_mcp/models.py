"""
Focused data models for reduced scope MCP server.

Unified AnalysisResult model for all content types with transparent freshness tracking.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, validator


class ScopeLevel(str, Enum):
    """Hierarchical scope levels for organizing knowledge."""

    PROJECT = "project"
    DOMAIN = "domain"
    MODULE = "module"
    FILE = "file"


class AnalysisType(str, Enum):
    """Types of analysis that can be stored."""

    DOCUMENT = "document"  # Documentation content
    ARCHITECTURE = "architecture"  # Component architecture
    DECISION = "decision"  # Design decisions
    STRUCTURE = "structure"  # Project structure
    SEMANTIC = "semantic"  # Semantic analysis
    DEPENDENCIES = "dependencies"  # Dependency analysis
    CROSS_PROJECT_LINK = "cross_project_link"  # Cross-project references


class FreshnessCategory(str, Enum):
    """Categories for freshness assessment."""

    FRESH = "fresh"  # < 1 hour old
    RECENT = "recent"  # 1 hour - 1 day old
    STALE = "stale"  # 1 day - 1 week old
    EXPIRED = "expired"  # > 1 week old


class ProjectContext(BaseModel):
    """Multi-project context for hierarchical knowledge organization."""

    project_id: str = Field(..., description="Unique project identifier")
    project_name: str = Field(..., description="Human-readable project name")
    project_root: str = Field(..., description="Absolute path to project root")

    # Hierarchical organization
    base_scope: str = Field(..., description="Base hierarchical scope (e.g., 'mycompany.frontend')")

    # Project metadata
    version: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    # Cross-project relationships
    parent_projects: List[str] = Field(default_factory=list, description="Parent project IDs")
    child_projects: List[str] = Field(default_factory=list, description="Child project IDs")
    linked_projects: List[str] = Field(default_factory=list, description="Related project IDs")

    # Configuration
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True

    def get_full_scope(self, sub_scope: str) -> str:
        """Generate full hierarchical scope including project context."""
        return f"{self.base_scope}.{sub_scope}"

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class CrossProjectReference(BaseModel):
    """Reference to analysis in another project."""

    source_project_id: str
    source_scope: str
    target_project_id: str
    target_scope: str

    # Reference metadata
    reference_type: str = Field(
        ..., description="Type of reference (dependency, inspiration, etc.)"
    )
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in reference relevance"
    )

    # Context
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = Field(None, description="Tool or user that created reference")

    # Bidirectional linking
    is_bidirectional: bool = Field(default=False, description="Whether reference works both ways")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class AnalysisResult(BaseModel):
    """Universal container for all analysis types with multi-project support."""

    id: UUID = Field(default_factory=uuid4)
    analysis_type: AnalysisType

    # Multi-project scope
    project_id: str = Field(..., description="Project this analysis belongs to")
    target_scope: str = Field(..., description="Hierarchical scope within project")
    full_scope: str = Field(..., description="Complete scope including project context")
    scope_level: ScopeLevel

    # Core data - polymorphic based on analysis_type
    result_data: Dict[str, Any] = Field(..., description="Analysis results in structured format")

    # Content addressing for change detection
    content_hash: str = Field(..., description="SHA-256 hash of source content")
    dependencies_hash: Optional[str] = Field(None, description="Hash of dependency inputs")

    # Source tracking
    source_files: List[str] = Field(default_factory=list)
    source_file_count: int = Field(0)

    # Cross-project references
    cross_project_refs: List[CrossProjectReference] = Field(default_factory=list)

    # Timing and performance
    analysis_timestamp: datetime = Field(default_factory=datetime.utcnow)
    analysis_duration_ms: Optional[int] = None

    # Vector embedding for semantic search
    vector_embedding: Optional[List[float]] = Field(None, description="1536-dim embedding vector")

    @validator("full_scope", always=True)
    def generate_full_scope(cls, v: str, values: Dict[str, Any]) -> str:
        """Generate full scope from project_id and target_scope."""
        project_id = values.get("project_id", "")
        target_scope = values.get("target_scope", "")

        if project_id and target_scope:
            return f"{project_id}.{target_scope}"
        return v or f"unknown.{target_scope}"

    @validator("source_file_count", always=True)
    def sync_file_count(cls, v: int, values: Dict[str, Any]) -> int:
        """Sync file count with source_files length."""
        source_files = values.get("source_files", [])
        return len(source_files)

    def extract_scope_hierarchy(self) -> Dict[str, str]:
        """Extract hierarchical components from full_scope."""
        parts = self.full_scope.split(".")

        hierarchy = {}
        if len(parts) >= 1:
            hierarchy["project"] = parts[0]
        if len(parts) >= 2:
            hierarchy["domain"] = parts[1]
        if len(parts) >= 3:
            hierarchy["module"] = parts[2]
        if len(parts) >= 4:
            hierarchy["component"] = parts[3]

        return hierarchy

    def add_cross_project_reference(
        self,
        target_project_id: str,
        target_scope: str,
        reference_type: str = "related",
        confidence_score: float = 0.8,
    ) -> None:
        """Add a cross-project reference."""
        ref = CrossProjectReference(
            source_project_id=self.project_id,
            source_scope=self.target_scope,
            target_project_id=target_project_id,
            target_scope=target_scope,
            reference_type=reference_type,
            confidence_score=confidence_score,
        )
        self.cross_project_refs.append(ref)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v),
        }


class FreshnessInfo(BaseModel):
    """Transparent freshness information using hierarchical timestamps."""

    staleness_seconds: float
    freshness_category: FreshnessCategory
    scope_last_change: datetime
    analysis_timestamp: datetime

    # Hierarchical context
    scope_path: str
    scope_level: ScopeLevel

    # Freshness scoring (0.0 = completely stale, 1.0 = perfectly fresh)
    freshness_score: float = Field(..., ge=0.0, le=1.0)

    # Actionable recommendations for agents
    recommendations: List[str] = Field(default_factory=list)

    @validator("freshness_category", always=True)
    def calculate_category(
        cls, v: Optional[FreshnessCategory], values: Dict[str, Any]
    ) -> FreshnessCategory:
        """Auto-calculate freshness category from staleness."""
        staleness = values.get("staleness_seconds", 0)

        if staleness < 3600:  # < 1 hour
            return FreshnessCategory.FRESH
        elif staleness < 86400:  # < 1 day
            return FreshnessCategory.RECENT
        elif staleness < 604800:  # < 1 week
            return FreshnessCategory.STALE
        else:
            return FreshnessCategory.EXPIRED

    @validator("freshness_score", always=True)
    def calculate_score(cls, v: Optional[float], values: Dict[str, Any]) -> float:
        """Calculate freshness score from staleness seconds."""
        staleness = values.get("staleness_seconds", 0)

        # Exponential decay: 1.0 at 0 seconds, 0.5 at 1 hour, 0.1 at 1 day
        if staleness <= 0:
            return 1.0

        # Use exponential decay with 1-hour half-life
        import math

        half_life_seconds = 3600  # 1 hour
        score = math.exp(-0.693 * staleness / half_life_seconds)

        return max(0.0, min(1.0, score))

    @validator("recommendations", always=True)
    def generate_recommendations(cls, v: List[str], values: Dict[str, Any]) -> List[str]:
        """Generate actionable recommendations based on freshness."""
        staleness = values.get("staleness_seconds", 0)
        scope_path = values.get("scope_path", "")

        if staleness < 60:  # < 1 minute
            return [f"✅ Fresh analysis of {scope_path}", "Safe to proceed with confidence"]
        elif staleness < 300:  # < 5 minutes
            return [
                f"📊 Analysis is {int(staleness)}s old, generally reliable",
                "Consider refreshing for critical decisions",
            ]
        elif staleness < 3600:  # < 1 hour
            return [
                f"⏰ Analysis is {int(staleness / 60)}m old, use with caution",
                "Recommend queuing refresh for accuracy",
            ]
        else:  # > 1 hour
            return [
                f"⚠️ Analysis is {int(staleness / 3600)}h old, refresh strongly recommended",
                "Queue high-priority refresh before making significant decisions",
            ]

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class QueryResult(BaseModel):
    """Complete tool response with analysis data and freshness context."""

    analysis_result: AnalysisResult
    freshness_info: FreshnessInfo

    # Performance metadata
    query_duration_ms: float
    cache_hit: bool = False
    retrieval_timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class SearchResult(BaseModel):
    """Semantic search result with scope context."""

    content_chunk: str = Field(..., description="Relevant text content")
    title: str = Field(default="", description="Content title or summary")
    scope: str = Field(..., description="Hierarchical scope of source")
    similarity_score: float = Field(..., ge=0.0, le=1.0, description="Cosine similarity score")
    analysis_type: AnalysisType = Field(default=AnalysisType.DOCUMENT)

    # Source metadata
    source_file: Optional[str] = None
    last_modified: Optional[datetime] = None
    content_hash: Optional[str] = None

    def extract_component_name(self) -> Optional[str]:
        """Extract component name from hierarchical scope."""
        parts = self.scope.split(".")
        if len(parts) >= 3 and parts[1] == "components":
            return parts[2]
        return None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class StorageRequest(BaseModel):
    """Request to store new analysis result."""

    analysis_type: AnalysisType
    target_scope: str
    scope_level: ScopeLevel
    content: str = Field(..., description="Raw content to analyze and store")

    # Optional metadata
    source_files: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    force_refresh: bool = Field(
        default=False, description="Force analysis even if content hash matches"
    )


class StorageResult(BaseModel):
    """Result from storing analysis data."""

    storage_id: UUID = Field(default_factory=uuid4)
    analysis_id: UUID
    was_deduplicated: bool = False
    existing_analysis_id: Optional[UUID] = None

    # Performance metrics
    storage_duration_ms: float
    analysis_duration_ms: Optional[float] = None
    storage_timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v),
        }


class HierarchicalTimestamp(BaseModel):
    """Timestamp tracking at hierarchical scope levels."""

    scope_path: str
    scope_level: ScopeLevel
    last_change: datetime
    change_source: Optional[str] = Field(
        None, description="File or component that triggered change"
    )
    change_type: str = Field(default="content_modified", description="Type of change")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class HealthStatus(BaseModel):
    """Health status for the knowledge store."""

    status: str = Field(..., description="Overall health status")
    database_connected: bool = False
    redis_connected: bool = False

    # Statistics
    total_analyses: int = 0
    total_scopes: int = 0
    cache_hit_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    # Performance metrics
    avg_query_time_ms: float = 0.0
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class LifecycleAction(str, Enum):
    """Actions for knowledge lifecycle management."""

    ARCHIVE = "archive"  # Move to archive storage
    DELETE = "delete"  # Permanently remove
    MARK_STALE = "mark_stale"  # Mark as stale but keep
    REFRESH = "refresh"  # Queue for refresh
    BULK_CLEANUP = "bulk_cleanup"  # Batch cleanup operations


class LifecycleRequest(BaseModel):
    """Request for knowledge lifecycle management operations."""

    action: LifecycleAction
    project_id: str = Field(..., description="Project ID to perform lifecycle action on")
    target_scope: Optional[str] = Field(None, description="Specific scope to target")
    analysis_ids: List[UUID] = Field(
        default_factory=list, description="Specific analysis IDs to target"
    )

    # Criteria for bulk operations
    older_than_days: Optional[int] = Field(None, description="Target items older than N days")
    analysis_types: List[AnalysisType] = Field(
        default_factory=list, description="Target specific analysis types"
    )
    staleness_threshold: Optional[float] = Field(
        None, description="Target items with staleness > threshold"
    )

    # Safety options
    dry_run: bool = Field(default=True, description="Preview operation without executing")
    batch_size: int = Field(default=100, description="Process in batches of N items")
    require_confirmation: bool = Field(default=True, description="Require explicit confirmation")

    # Archival options (when action=ARCHIVE)
    archive_reason: str = Field(default="", description="Reason for archival")
    retain_metadata: bool = Field(default=True, description="Keep metadata after archival")


class LifecycleResult(BaseModel):
    """Result from lifecycle management operations."""

    operation_id: UUID = Field(default_factory=uuid4)
    action_performed: LifecycleAction
    target_scope: Optional[str] = None

    # Operation results
    items_affected: int = 0
    items_archived: int = 0
    items_deleted: int = 0
    items_marked_stale: int = 0
    items_queued_refresh: int = 0

    # Safety and execution info
    was_dry_run: bool = True
    execution_timestamp: datetime = Field(default_factory=datetime.utcnow)
    operation_duration_ms: float = 0.0

    # Detailed results
    affected_analysis_ids: List[UUID] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    # Storage impact
    storage_freed_bytes: Optional[int] = None
    cache_entries_cleared: int = 0

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v),
        }


class ArchivedAnalysis(BaseModel):
    """Metadata for archived analysis results."""

    original_id: UUID
    archived_at: datetime = Field(default_factory=datetime.utcnow)
    archive_reason: str
    original_scope: str
    original_analysis_type: AnalysisType

    # Retention metadata
    original_timestamp: datetime
    source_files: List[str] = Field(default_factory=list)
    content_hash: str

    # Archive storage info
    archive_location: Optional[str] = None
    compressed_size_bytes: Optional[int] = None
    can_restore: bool = True

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v),
        }


class CleanupPolicy(BaseModel):
    """Configuration for automated cleanup policies."""

    policy_name: str
    enabled: bool = True

    # Trigger conditions
    max_age_days: Optional[int] = Field(None, description="Auto-archive after N days")
    max_staleness_hours: Optional[int] = Field(None, description="Auto-mark-stale after N hours")
    storage_threshold_mb: Optional[int] = Field(
        None, description="Cleanup when storage exceeds N MB"
    )

    # Scope targeting
    target_scopes: List[str] = Field(default_factory=list)
    target_analysis_types: List[AnalysisType] = Field(default_factory=list)
    exclude_scopes: List[str] = Field(default_factory=list)

    # Safety settings
    require_manual_approval: bool = True
    max_items_per_run: int = 1000
    dry_run_first: bool = True

    # Schedule
    run_frequency_hours: int = 24  # Daily by default
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
