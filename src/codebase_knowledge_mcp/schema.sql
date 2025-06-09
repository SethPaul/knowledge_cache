-- Reduced Scope MCP Server Database Schema
-- PostgreSQL with pgvector extension for semantic search

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgvector";
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Project context and multi-project management
CREATE TABLE IF NOT EXISTS project_contexts (
    project_id TEXT PRIMARY KEY,
    project_name TEXT NOT NULL,
    project_root TEXT NOT NULL,
    base_scope TEXT NOT NULL,
    
    -- Project metadata
    version TEXT,
    description TEXT,
    tags TEXT[] DEFAULT '{}',
    
    -- Cross-project relationships (stored as arrays for simplicity)
    parent_projects TEXT[] DEFAULT '{}',
    child_projects TEXT[] DEFAULT '{}', 
    linked_projects TEXT[] DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Indexing
    UNIQUE(project_root),
    UNIQUE(base_scope)
);

-- Cross-project references table
CREATE TABLE IF NOT EXISTS cross_project_references (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Source reference
    source_project_id TEXT NOT NULL REFERENCES project_contexts(project_id),
    source_scope TEXT NOT NULL,
    
    -- Target reference  
    target_project_id TEXT NOT NULL REFERENCES project_contexts(project_id),
    target_scope TEXT NOT NULL,
    
    -- Reference metadata
    reference_type TEXT NOT NULL DEFAULT 'related',
    confidence_score FLOAT NOT NULL DEFAULT 0.8 CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
    
    -- Context
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by TEXT,
    is_bidirectional BOOLEAN DEFAULT FALSE,
    
    -- Prevent duplicate references
    UNIQUE(source_project_id, source_scope, target_project_id, target_scope, reference_type)
);

-- Enhanced analysis results with multi-project support
CREATE TABLE IF NOT EXISTS analysis_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_type TEXT NOT NULL,
    
    -- Multi-project scope
    project_id TEXT NOT NULL REFERENCES project_contexts(project_id),
    target_scope TEXT NOT NULL,
    full_scope TEXT NOT NULL,
    scope_level TEXT NOT NULL,
    
    -- Core data (stored as JSONB for flexibility)
    result_data JSONB NOT NULL,
    
    -- Content addressing for change detection
    content_hash TEXT NOT NULL,
    dependencies_hash TEXT,
    
    -- Source tracking
    source_files TEXT[] DEFAULT '{}',
    source_file_count INTEGER DEFAULT 0,
    
    -- Timing and performance
    analysis_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    analysis_duration_ms INTEGER,
    
    -- Vector embedding for semantic search (1536 dimensions for OpenAI)
    vector_embedding vector(384),
    
    -- Indexing and constraints
    UNIQUE(project_id, target_scope, analysis_type, content_hash)
);

-- Separate table for storing cross-project references within analysis results
-- (for better normalization and querying)
CREATE TABLE IF NOT EXISTS analysis_cross_refs (
    analysis_id UUID REFERENCES analysis_results(id) ON DELETE CASCADE,
    cross_ref_id UUID REFERENCES cross_project_references(id) ON DELETE CASCADE,
    PRIMARY KEY (analysis_id, cross_ref_id)
);

-- Keep existing lifecycle tables with project awareness
CREATE TABLE IF NOT EXISTS archived_analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Original analysis metadata
    original_id UUID NOT NULL,
    project_id TEXT NOT NULL REFERENCES project_contexts(project_id),
    analysis_type TEXT NOT NULL,
    target_scope TEXT NOT NULL,
    full_scope TEXT NOT NULL,
    
    -- Archived content
    archived_result_data JSONB NOT NULL,
    archive_reason TEXT NOT NULL,
    
    -- Timestamps
    original_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    archived_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    archived_by TEXT,
    
    -- Search metadata (for quick retrieval without full deserialization)
    search_metadata JSONB DEFAULT '{}',
    
    UNIQUE(original_id, archived_at)
);

-- Enhanced cleanup policies with project scope
CREATE TABLE IF NOT EXISTS cleanup_policies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    policy_name TEXT NOT NULL,
    project_scope TEXT, -- NULL means applies to all projects
    target_analysis_types TEXT[] DEFAULT '{}', -- Empty means all types
    
    -- Age-based cleanup
    max_age_days INTEGER NOT NULL DEFAULT 90,
    staleness_threshold_days INTEGER DEFAULT 7,
    
    -- Volume-based cleanup
    max_items_per_scope INTEGER,
    keep_recent_count INTEGER DEFAULT 10,
    
    -- Execution control
    is_active BOOLEAN DEFAULT TRUE,
    dry_run BOOLEAN DEFAULT TRUE,
    schedule_cron TEXT DEFAULT '0 2 * * 0', -- Weekly at 2 AM
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by TEXT,
    last_executed TIMESTAMP WITH TIME ZONE,
    
    UNIQUE(policy_name)
);

-- Enhanced lifecycle operations with project tracking
CREATE TABLE IF NOT EXISTS lifecycle_operations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    operation_type TEXT NOT NULL,
    project_id TEXT REFERENCES project_contexts(project_id),
    target_scope TEXT,
    
    -- Operation details
    affected_count INTEGER DEFAULT 0,
    operation_details JSONB DEFAULT '{}',
    
    -- Results
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    error_details JSONB DEFAULT '{}',
    
    -- Execution metadata
    executed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    executed_by TEXT,
    execution_duration_ms INTEGER,
    
    -- Policy context
    policy_id UUID REFERENCES cleanup_policies(id),
    is_dry_run BOOLEAN DEFAULT TRUE
);

-- Hierarchical timestamp tracking for freshness management
CREATE TABLE hierarchical_timestamps (
    scope_path TEXT NOT NULL,
    scope_level TEXT NOT NULL CHECK (scope_level IN ('project', 'domain', 'module', 'file')),
    last_change TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    change_source TEXT,
    change_type TEXT DEFAULT 'content_modified',
    
    PRIMARY KEY (scope_path, scope_level)
);

-- Simple cache table for Redis overflow/persistence
CREATE TABLE cache_entries (
    cache_key TEXT PRIMARY KEY,
    cache_data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    access_count INTEGER DEFAULT 1,
    last_accessed TIMESTAMPTZ DEFAULT NOW()
);

-- Cleanup policies for automated lifecycle management
CREATE TABLE cleanup_policies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    policy_name TEXT UNIQUE NOT NULL,
    enabled BOOLEAN DEFAULT true,
    
    -- Trigger conditions
    max_age_days INTEGER,
    max_staleness_hours INTEGER,
    storage_threshold_mb INTEGER,
    
    -- Targeting
    target_scopes TEXT[] DEFAULT '{}',
    target_analysis_types TEXT[] DEFAULT '{}',
    exclude_scopes TEXT[] DEFAULT '{}',
    
    -- Safety settings
    require_manual_approval BOOLEAN DEFAULT true,
    max_items_per_run INTEGER DEFAULT 1000,
    dry_run_first BOOLEAN DEFAULT true,
    
    -- Schedule
    run_frequency_hours INTEGER DEFAULT 24,
    last_run TIMESTAMPTZ,
    next_run TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Lifecycle operation audit log
CREATE TABLE lifecycle_operations (
    operation_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    action_performed TEXT NOT NULL CHECK (action_performed IN ('archive', 'delete', 'mark_stale', 'refresh', 'bulk_cleanup')),
    target_scope TEXT,
    
    -- Operation results
    items_affected INTEGER DEFAULT 0,
    items_archived INTEGER DEFAULT 0,
    items_deleted INTEGER DEFAULT 0,
    items_marked_stale INTEGER DEFAULT 0,
    items_queued_refresh INTEGER DEFAULT 0,
    
    -- Execution info
    was_dry_run BOOLEAN DEFAULT true,
    execution_timestamp TIMESTAMPTZ DEFAULT NOW(),
    operation_duration_ms FLOAT,
    
    -- Detailed tracking
    affected_analysis_ids UUID[] DEFAULT '{}',
    errors TEXT[] DEFAULT '{}',
    warnings TEXT[] DEFAULT '{}',
    
    -- Storage impact
    storage_freed_bytes BIGINT,
    cache_entries_cleared INTEGER DEFAULT 0,
    
    -- Request context
    requested_by TEXT,
    request_details JSONB
);

-- Performance indexes
CREATE INDEX idx_analysis_results_scope ON analysis_results(target_scope, scope_level);
CREATE INDEX idx_analysis_results_type ON analysis_results(analysis_type);
CREATE INDEX idx_analysis_results_timestamp ON analysis_results(analysis_timestamp DESC);
CREATE INDEX idx_analysis_results_content_hash ON analysis_results(content_hash);

-- Vector similarity search index (HNSW for performance)
CREATE INDEX idx_analysis_results_vector ON analysis_results USING hnsw (vector_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Hierarchical timestamps indexes
CREATE INDEX idx_hierarchical_timestamps_scope ON hierarchical_timestamps(scope_path);
CREATE INDEX idx_hierarchical_timestamps_level ON hierarchical_timestamps(scope_level);
CREATE INDEX idx_hierarchical_timestamps_change ON hierarchical_timestamps(last_change DESC);

-- Cache indexes
CREATE INDEX idx_cache_entries_expires ON cache_entries(expires_at);
CREATE INDEX idx_cache_entries_created ON cache_entries(created_at DESC);

-- Archive indexes
CREATE INDEX idx_archived_analyses_original_id ON archived_analyses(original_id);
CREATE INDEX idx_archived_analyses_scope ON archived_analyses(original_scope);
CREATE INDEX idx_archived_analyses_type ON archived_analyses(original_analysis_type);
CREATE INDEX idx_archived_analyses_archived_at ON archived_analyses(archived_at DESC);
CREATE INDEX idx_archived_analyses_can_restore ON archived_analyses(can_restore) WHERE can_restore = true;

-- Cleanup policy indexes
CREATE INDEX idx_cleanup_policies_enabled ON cleanup_policies(enabled) WHERE enabled = true;
CREATE INDEX idx_cleanup_policies_next_run ON cleanup_policies(next_run) WHERE enabled = true AND next_run IS NOT NULL;

-- Lifecycle operations indexes
CREATE INDEX idx_lifecycle_operations_timestamp ON lifecycle_operations(execution_timestamp DESC);
CREATE INDEX idx_lifecycle_operations_action ON lifecycle_operations(action_performed);
CREATE INDEX idx_lifecycle_operations_scope ON lifecycle_operations(target_scope);
CREATE INDEX idx_lifecycle_operations_dry_run ON lifecycle_operations(was_dry_run);

-- GIN index for JSONB queries on result_data
CREATE INDEX idx_analysis_results_data_gin ON analysis_results USING gin(result_data);

-- Text search index for content
CREATE INDEX idx_analysis_results_text_search ON analysis_results USING gin(to_tsvector('english', result_data::text));

-- Partial indexes for common queries
CREATE INDEX idx_analysis_results_recent ON analysis_results(analysis_timestamp DESC) 
    WHERE analysis_timestamp > NOW() - INTERVAL '7 days';

CREATE INDEX idx_analysis_results_architecture ON analysis_results(target_scope, analysis_timestamp DESC)
    WHERE analysis_type = 'architecture';

-- Helper functions for hierarchical scope operations
CREATE OR REPLACE FUNCTION get_scope_hierarchy(scope_path TEXT)
RETURNS TABLE(level TEXT, path TEXT) AS $$
BEGIN
    DECLARE
        parts TEXT[];
        i INTEGER;
    BEGIN
        parts := string_to_array(scope_path, '.');
        
        -- Return project level
        IF array_length(parts, 1) >= 1 THEN
            RETURN QUERY SELECT 'project'::TEXT, parts[1];
        END IF;
        
        -- Return domain level  
        IF array_length(parts, 1) >= 2 THEN
            RETURN QUERY SELECT 'domain'::TEXT, parts[1] || '.' || parts[2];
        END IF;
        
        -- Return module level
        IF array_length(parts, 1) >= 3 THEN
            RETURN QUERY SELECT 'module'::TEXT, parts[1] || '.' || parts[2] || '.' || parts[3];
        END IF;
        
        -- Return file level (full path)
        IF array_length(parts, 1) >= 4 THEN
            RETURN QUERY SELECT 'file'::TEXT, scope_path;
        END IF;
    END;
END;
$$ LANGUAGE plpgsql;

-- Function to update hierarchical timestamps
CREATE OR REPLACE FUNCTION update_hierarchical_timestamps(
    p_scope_path TEXT,
    p_change_source TEXT DEFAULT NULL,
    p_change_type TEXT DEFAULT 'content_modified'
) RETURNS VOID AS $$
DECLARE
    scope_rec RECORD;
BEGIN
    -- Update timestamps at all relevant hierarchical levels
    FOR scope_rec IN SELECT level, path FROM get_scope_hierarchy(p_scope_path) LOOP
        INSERT INTO hierarchical_timestamps (scope_path, scope_level, last_change, change_source, change_type)
        VALUES (scope_rec.path, scope_rec.level, NOW(), p_change_source, p_change_type)
        ON CONFLICT (scope_path, scope_level) 
        DO UPDATE SET 
            last_change = NOW(),
            change_source = EXCLUDED.change_source,
            change_type = EXCLUDED.change_type;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Function for semantic similarity search
CREATE OR REPLACE FUNCTION semantic_search(
    query_embedding vector(1536),
    p_analysis_type TEXT DEFAULT NULL,
    p_scope_filter TEXT DEFAULT NULL,
    p_limit INTEGER DEFAULT 10
) RETURNS TABLE(
    id UUID,
    target_scope TEXT,
    analysis_type TEXT,
    similarity_score FLOAT,
    result_data JSONB,
    analysis_timestamp TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ar.id,
        ar.target_scope,
        ar.analysis_type,
        1 - (ar.vector_embedding <=> query_embedding) AS similarity_score,
        ar.result_data,
        ar.analysis_timestamp
    FROM analysis_results ar
    WHERE 
        ar.vector_embedding IS NOT NULL
        AND (p_analysis_type IS NULL OR ar.analysis_type = p_analysis_type)
        AND (p_scope_filter IS NULL OR ar.target_scope LIKE p_scope_filter || '%')
    ORDER BY ar.vector_embedding <=> query_embedding
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- Function to get freshness information
CREATE OR REPLACE FUNCTION get_freshness_info(
    p_analysis_id UUID
) RETURNS TABLE(
    analysis_timestamp TIMESTAMPTZ,
    scope_last_change TIMESTAMPTZ,
    staleness_seconds FLOAT,
    scope_path TEXT,
    scope_level TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ar.analysis_timestamp,
        COALESCE(ht.last_change, ar.analysis_timestamp) AS scope_last_change,
        EXTRACT(EPOCH FROM (COALESCE(ht.last_change, ar.analysis_timestamp) - ar.analysis_timestamp)) AS staleness_seconds,
        ar.target_scope AS scope_path,
        ar.scope_level
    FROM analysis_results ar
    LEFT JOIN hierarchical_timestamps ht ON (
        ht.scope_path = ar.target_scope AND ht.scope_level = ar.scope_level
    )
    WHERE ar.id = p_analysis_id;
END;
$$ LANGUAGE plpgsql;

-- Function to archive analysis results
CREATE OR REPLACE FUNCTION archive_analysis_result(
    p_analysis_id UUID,
    p_archive_reason TEXT,
    p_retain_summary BOOLEAN DEFAULT true
) RETURNS BOOLEAN AS $$
DECLARE
    analysis_rec RECORD;
    summary_data JSONB;
BEGIN
    -- Get the analysis to archive
    SELECT * INTO analysis_rec FROM analysis_results WHERE id = p_analysis_id;
    
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;
    
    -- Create summary if requested
    IF p_retain_summary THEN
        summary_data := jsonb_build_object(
            'title', COALESCE(analysis_rec.result_data->>'title', 'No title'),
            'summary', LEFT(COALESCE(analysis_rec.result_data->>'content', ''), 500),
            'key_points', analysis_rec.result_data->'key_points'
        );
    END IF;
    
    -- Insert into archive
    INSERT INTO archived_analyses (
        original_id, archive_reason, original_scope, original_analysis_type,
        original_timestamp, source_files, content_hash, archive_summary
    ) VALUES (
        analysis_rec.id, p_archive_reason, analysis_rec.target_scope, analysis_rec.analysis_type,
        analysis_rec.analysis_timestamp, analysis_rec.source_files, analysis_rec.content_hash, summary_data
    );
    
    -- Remove from active results
    DELETE FROM analysis_results WHERE id = p_analysis_id;
    
    -- Update hierarchical timestamp
    PERFORM update_hierarchical_timestamps(
        analysis_rec.target_scope,
        'archived_analysis',
        'analysis_archived'
    );
    
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function to bulk cleanup stale analysis results
CREATE OR REPLACE FUNCTION cleanup_stale_analyses(
    p_staleness_days INTEGER DEFAULT 30,
    p_target_scope_pattern TEXT DEFAULT '%',
    p_analysis_types TEXT[] DEFAULT '{}',
    p_dry_run BOOLEAN DEFAULT true,
    p_batch_size INTEGER DEFAULT 100
) RETURNS TABLE(
    total_candidates INTEGER,
    items_processed INTEGER,
    items_archived INTEGER,
    items_deleted INTEGER,
    storage_freed_bytes BIGINT
) AS $$
DECLARE
    candidate_count INTEGER;
    processed_count INTEGER := 0;
    archived_count INTEGER := 0;
    deleted_count INTEGER := 0;
    freed_bytes BIGINT := 0;
    analysis_rec RECORD;
    staleness_threshold TIMESTAMPTZ;
BEGIN
    staleness_threshold := NOW() - (p_staleness_days || ' days')::INTERVAL;
    
    -- Count candidates
    SELECT COUNT(*) INTO candidate_count 
    FROM analysis_results ar
    WHERE ar.analysis_timestamp < staleness_threshold
      AND ar.target_scope LIKE p_target_scope_pattern
      AND (array_length(p_analysis_types, 1) = 0 OR ar.analysis_type = ANY(p_analysis_types));
    
    -- Process in batches
    FOR analysis_rec IN 
        SELECT * FROM analysis_results ar
        WHERE ar.analysis_timestamp < staleness_threshold
          AND ar.target_scope LIKE p_target_scope_pattern
          AND (array_length(p_analysis_types, 1) = 0 OR ar.analysis_type = ANY(p_analysis_types))
        ORDER BY ar.analysis_timestamp ASC
        LIMIT p_batch_size
    LOOP
        processed_count := processed_count + 1;
        
        IF NOT p_dry_run THEN
            -- Archive the analysis
            IF archive_analysis_result(
                analysis_rec.id, 
                'Automated cleanup - stale data older than ' || p_staleness_days || ' days'
            ) THEN
                archived_count := archived_count + 1;
                -- Estimate freed storage (rough calculation)
                freed_bytes := freed_bytes + length(analysis_rec.result_data::text) + 
                              COALESCE(array_length(analysis_rec.vector_embedding, 1) * 4, 0);
            END IF;
        END IF;
    END LOOP;
    
    RETURN QUERY SELECT candidate_count, processed_count, archived_count, deleted_count, freed_bytes;
END;
$$ LANGUAGE plpgsql;

-- Function to restore archived analysis
CREATE OR REPLACE FUNCTION restore_archived_analysis(
    p_archive_id UUID
) RETURNS BOOLEAN AS $$
DECLARE
    archive_rec RECORD;
BEGIN
    -- Get archived analysis
    SELECT * INTO archive_rec FROM archived_analyses WHERE id = p_archive_id AND can_restore = true;
    
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;
    
    -- Note: This is a placeholder - full restoration would require retrieving 
    -- the complete result_data from archive storage
    -- For now, we just mark as non-restorable to prevent confusion
    UPDATE archived_analyses SET can_restore = false WHERE id = p_archive_id;
    
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function to execute cleanup policies
CREATE OR REPLACE FUNCTION execute_cleanup_policies() 
RETURNS TABLE(
    policy_name TEXT,
    execution_status TEXT,
    items_processed INTEGER,
    next_execution TIMESTAMPTZ
) AS $$
DECLARE
    policy_rec RECORD;
    cleanup_result RECORD;
    next_run TIMESTAMPTZ;
BEGIN
    FOR policy_rec IN 
        SELECT * FROM cleanup_policies 
        WHERE enabled = true 
          AND (next_run IS NULL OR next_run <= NOW())
    LOOP
        -- Execute the cleanup policy
        IF policy_rec.max_age_days IS NOT NULL THEN
            SELECT * INTO cleanup_result FROM cleanup_stale_analyses(
                policy_rec.max_age_days,
                COALESCE(array_to_string(policy_rec.target_scopes, '|'), '%'),
                policy_rec.target_analysis_types,
                policy_rec.dry_run_first,
                policy_rec.max_items_per_run
            );
            
            -- Update policy run timestamp
            next_run := NOW() + (policy_rec.run_frequency_hours || ' hours')::INTERVAL;
            UPDATE cleanup_policies 
            SET last_run = NOW(), next_run = next_run 
            WHERE id = policy_rec.id;
            
            RETURN QUERY SELECT 
                policy_rec.policy_name,
                'completed'::TEXT,
                cleanup_result.items_processed,
                next_run;
        ELSE
            RETURN QUERY SELECT 
                policy_rec.policy_name,
                'skipped - no criteria'::TEXT,
                0,
                next_run;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update hierarchical timestamps when analysis_results change
CREATE OR REPLACE FUNCTION trigger_update_hierarchical_timestamps()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        PERFORM update_hierarchical_timestamps(
            NEW.target_scope,
            'analysis_result',
            CASE WHEN TG_OP = 'INSERT' THEN 'analysis_created' ELSE 'analysis_updated' END
        );
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_analysis_results_timestamps
    AFTER INSERT OR UPDATE ON analysis_results
    FOR EACH ROW EXECUTE FUNCTION trigger_update_hierarchical_timestamps();

-- Cache cleanup function (remove expired entries)
CREATE OR REPLACE FUNCTION cleanup_expired_cache()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM cache_entries WHERE expires_at < NOW();
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Create a simple health check view
CREATE OR REPLACE VIEW health_status AS
SELECT 
    'healthy' AS status,
    COUNT(*)::INTEGER AS total_analyses,
    COUNT(DISTINCT target_scope)::INTEGER AS total_scopes,
    COUNT(*) FILTER (WHERE analysis_timestamp > NOW() - INTERVAL '1 hour')::INTEGER AS recent_analyses,
    COUNT(*) FILTER (WHERE vector_embedding IS NOT NULL)::INTEGER AS analyses_with_embeddings,
    MAX(analysis_timestamp) AS last_analysis_timestamp
FROM analysis_results;

-- Indexes for the health view
CREATE INDEX idx_health_recent_analyses ON analysis_results(analysis_timestamp) 
    WHERE analysis_timestamp > NOW() - INTERVAL '1 hour';

-- Comments for documentation
COMMENT ON TABLE analysis_results IS 'Universal storage for all analysis types with vector embeddings';
COMMENT ON TABLE hierarchical_timestamps IS 'Timestamp tracking at hierarchical scope levels for freshness management';
COMMENT ON TABLE cache_entries IS 'Simple cache overflow/persistence for Redis';

COMMENT ON FUNCTION get_scope_hierarchy(TEXT) IS 'Extract hierarchical scope components from dot-notation path';
COMMENT ON FUNCTION update_hierarchical_timestamps(TEXT, TEXT, TEXT) IS 'Update timestamps at all relevant hierarchical levels';
COMMENT ON FUNCTION semantic_search(vector(1536), TEXT, TEXT, INTEGER) IS 'Semantic similarity search using vector embeddings';
COMMENT ON FUNCTION get_freshness_info(UUID) IS 'Get staleness information for an analysis result';

-- Grant permissions (adjust as needed for your environment)
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO knowledge_user;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO knowledge_user;
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO knowledge_user;

-- Project context indexes
CREATE INDEX IF NOT EXISTS idx_project_contexts_active ON project_contexts(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_project_contexts_tags ON project_contexts USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_project_contexts_updated ON project_contexts(last_updated);

-- Cross-project reference indexes
CREATE INDEX IF NOT EXISTS idx_cross_refs_source ON cross_project_references(source_project_id, source_scope);
CREATE INDEX IF NOT EXISTS idx_cross_refs_target ON cross_project_references(target_project_id, target_scope);
CREATE INDEX IF NOT EXISTS idx_cross_refs_type ON cross_project_references(reference_type);
CREATE INDEX IF NOT EXISTS idx_cross_refs_confidence ON cross_project_references(confidence_score);

-- Analysis results indexes (enhanced for multi-project)
CREATE INDEX IF NOT EXISTS idx_analysis_project_scope ON analysis_results(project_id, target_scope);
CREATE INDEX IF NOT EXISTS idx_analysis_project_type ON analysis_results(project_id, analysis_type);
CREATE INDEX IF NOT EXISTS idx_analysis_full_scope ON analysis_results(full_scope);
CREATE INDEX IF NOT EXISTS idx_analysis_content_hash ON analysis_results(content_hash);
CREATE INDEX IF NOT EXISTS idx_analysis_timestamp ON analysis_results(analysis_timestamp);
CREATE INDEX IF NOT EXISTS idx_analysis_scope_level ON analysis_results(scope_level);

-- Vector similarity search index
CREATE INDEX IF NOT EXISTS idx_analysis_vector ON analysis_results USING ivfflat (vector_embedding vector_cosine_ops)
WITH (lists = 100);

-- Text search indexes
CREATE INDEX IF NOT EXISTS idx_analysis_result_data_gin ON analysis_results USING GIN(result_data);
CREATE INDEX IF NOT EXISTS idx_analysis_source_files_gin ON analysis_results USING GIN(source_files);

-- Lifecycle indexes with project awareness
CREATE INDEX IF NOT EXISTS idx_archived_project_scope ON archived_analyses(project_id, target_scope);
CREATE INDEX IF NOT EXISTS idx_archived_timestamp ON archived_analyses(original_timestamp);
CREATE INDEX IF NOT EXISTS idx_cleanup_policies_active ON cleanup_policies(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_cleanup_policies_project ON cleanup_policies(project_scope);
CREATE INDEX IF NOT EXISTS idx_lifecycle_ops_project ON lifecycle_operations(project_id, operation_type);
CREATE INDEX IF NOT EXISTS idx_lifecycle_ops_timestamp ON lifecycle_operations(executed_at);

-- Functions for multi-project operations

-- Get project hierarchy (parent/child relationships)
CREATE OR REPLACE FUNCTION get_project_hierarchy(input_project_id TEXT)
RETURNS JSONB AS $$
DECLARE
    result JSONB;
BEGIN
    WITH RECURSIVE project_tree AS (
        -- Base case: start with the input project
        SELECT 
            project_id,
            project_name,
            parent_projects,
            child_projects,
            0 as level,
            ARRAY[project_id] as path
        FROM project_contexts 
        WHERE project_id = input_project_id AND is_active = TRUE
        
        UNION ALL
        
        -- Recursive case: find children
        SELECT 
            pc.project_id,
            pc.project_name,
            pc.parent_projects,
            pc.child_projects,
            pt.level + 1,
            pt.path || pc.project_id
        FROM project_contexts pc
        JOIN project_tree pt ON pc.project_id = ANY(pt.child_projects)
        WHERE pt.level < 10 -- Prevent infinite recursion
        AND NOT pc.project_id = ANY(pt.path) -- Prevent cycles
        AND pc.is_active = TRUE
    )
    SELECT jsonb_agg(
        jsonb_build_object(
            'project_id', project_id,
            'project_name', project_name,
            'level', level,
            'path', path
        )
    ) INTO result
    FROM project_tree;
    
    RETURN COALESCE(result, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql;

-- Find cross-project references for a given scope
CREATE OR REPLACE FUNCTION find_cross_project_references(
    input_project_id TEXT,
    input_scope TEXT DEFAULT NULL,
    reference_types TEXT[] DEFAULT NULL
)
RETURNS JSONB AS $$
DECLARE
    result JSONB;
BEGIN
    SELECT jsonb_agg(
        jsonb_build_object(
            'reference_id', cpr.id,
            'source_project', src.project_name,
            'source_scope', cpr.source_scope,
            'target_project', tgt.project_name,
            'target_scope', cpr.target_scope,
            'reference_type', cpr.reference_type,
            'confidence_score', cpr.confidence_score,
            'created_at', cpr.created_at,
            'is_bidirectional', cpr.is_bidirectional
        )
    ) INTO result
    FROM cross_project_references cpr
    JOIN project_contexts src ON cpr.source_project_id = src.project_id
    JOIN project_contexts tgt ON cpr.target_project_id = tgt.project_id
    WHERE (cpr.source_project_id = input_project_id OR cpr.target_project_id = input_project_id)
    AND (input_scope IS NULL OR cpr.source_scope LIKE input_scope || '%' OR cpr.target_scope LIKE input_scope || '%')
    AND (reference_types IS NULL OR cpr.reference_type = ANY(reference_types))
    AND src.is_active = TRUE 
    AND tgt.is_active = TRUE;
    
    RETURN COALESCE(result, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql;

-- Enhanced cleanup function with project awareness
CREATE OR REPLACE FUNCTION cleanup_stale_analyses_by_project(
    target_project_id TEXT,
    staleness_days INTEGER DEFAULT 7,
    max_cleanup_count INTEGER DEFAULT 1000,
    dry_run BOOLEAN DEFAULT TRUE
)
RETURNS JSONB AS $$
DECLARE
    cleanup_count INTEGER;
    operation_id UUID;
    start_time TIMESTAMP := NOW();
BEGIN
    -- Create operation record
    INSERT INTO lifecycle_operations (
        operation_type, project_id, 
        operation_details, is_dry_run
    ) VALUES (
        'cleanup_stale_project', target_project_id,
        jsonb_build_object(
            'staleness_days', staleness_days,
            'max_cleanup_count', max_cleanup_count
        ),
        dry_run
    ) RETURNING id INTO operation_id;
    
    IF dry_run THEN
        -- Count what would be cleaned up
        SELECT COUNT(*) INTO cleanup_count
        FROM analysis_results ar
        WHERE ar.project_id = target_project_id
        AND ar.analysis_timestamp < NOW() - (staleness_days || ' days')::INTERVAL
        LIMIT max_cleanup_count;
    ELSE
        -- Archive stale analyses
        WITH stale_analyses AS (
            SELECT id, project_id, analysis_type, target_scope, full_scope, result_data, analysis_timestamp
            FROM analysis_results 
            WHERE project_id = target_project_id
            AND analysis_timestamp < NOW() - (staleness_days || ' days')::INTERVAL
            LIMIT max_cleanup_count
        ),
        archived AS (
            INSERT INTO archived_analyses (
                original_id, project_id, analysis_type, target_scope, full_scope,
                archived_result_data, archive_reason, original_timestamp
            )
            SELECT 
                id, project_id, analysis_type, target_scope, full_scope,
                result_data, 'stale_cleanup', analysis_timestamp
            FROM stale_analyses
            RETURNING original_id
        )
        DELETE FROM analysis_results 
        WHERE id IN (SELECT original_id FROM archived)
        RETURNING 1;
        
        GET DIAGNOSTICS cleanup_count = ROW_COUNT;
    END IF;
    
    -- Update operation record
    UPDATE lifecycle_operations SET
        success_count = cleanup_count,
        execution_duration_ms = EXTRACT(EPOCH FROM (NOW() - start_time)) * 1000
    WHERE id = operation_id;
    
    RETURN jsonb_build_object(
        'operation_id', operation_id,
        'project_id', target_project_id,
        'cleaned_count', cleanup_count,
        'dry_run', dry_run,
        'staleness_days', staleness_days
    );
END;
$$ LANGUAGE plpgsql; 