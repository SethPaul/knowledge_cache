-- Import the full comprehensive schema
-- This includes all functionality with adaptive pgvector support
\ir /docker-entrypoint-initdb.d/03-full-schema.sql

-- Check for pgvector availability and configure accordingly
DO $$
DECLARE
    has_pgvector boolean := false;
BEGIN
    -- Check if vector extension exists
    SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector') INTO has_pgvector;
    
    IF has_pgvector THEN
        RAISE NOTICE 'pgvector extension available - vector search enabled';
    ELSE
        RAISE NOTICE 'pgvector extension not available - vector search disabled';
    END IF;
END $$;

-- Project contexts for multi-project support
CREATE TABLE IF NOT EXISTS project_contexts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    settings JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Analysis results with optional vector support
CREATE TABLE IF NOT EXISTS analysis_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_type TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT 'default',
    target_scope TEXT NOT NULL,
    full_scope TEXT NOT NULL,
    scope_level TEXT NOT NULL,
    result_data JSONB NOT NULL,
    content_hash TEXT NOT NULL,
    dependencies_hash TEXT,
    source_files TEXT[] DEFAULT '{}',
    source_file_count INTEGER DEFAULT 0,
    analysis_timestamp TIMESTAMPTZ DEFAULT NOW(),
    analysis_duration_ms INTEGER,
    
    CONSTRAINT analysis_results_unique_content 
        UNIQUE (project_id, target_scope, analysis_type, content_hash)
);

-- Add vector column if pgvector is available
DO $$
DECLARE
    has_pgvector boolean := false;
    column_exists boolean := false;
BEGIN
    -- Check if vector extension exists
    SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector') INTO has_pgvector;
    
    -- Check if vector_embedding column already exists
    SELECT EXISTS(
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'analysis_results' 
        AND column_name = 'vector_embedding'
    ) INTO column_exists;
    
    IF has_pgvector AND NOT column_exists THEN
        ALTER TABLE analysis_results ADD COLUMN vector_embedding vector(384);
        RAISE NOTICE 'Added vector_embedding column - semantic search enabled';
    ELSIF NOT has_pgvector THEN
        RAISE NOTICE 'pgvector not available - semantic search disabled';
    END IF;
END $$;

-- Hierarchical timestamps for change tracking
CREATE TABLE IF NOT EXISTS hierarchical_timestamps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id TEXT NOT NULL DEFAULT 'default',
    scope_path TEXT NOT NULL,
    scope_level TEXT NOT NULL,
    last_change TIMESTAMPTZ DEFAULT NOW(),
    change_count INTEGER DEFAULT 1,
    
    CONSTRAINT hierarchical_timestamps_unique_scope 
        UNIQUE (project_id, scope_path)
);

-- Cache entries for performance optimization
CREATE TABLE IF NOT EXISTS cache_entries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cache_key TEXT NOT NULL UNIQUE,
    cache_data JSONB NOT NULL,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Basic indexes
CREATE INDEX IF NOT EXISTS idx_analysis_results_scope ON analysis_results(target_scope, scope_level);
CREATE INDEX IF NOT EXISTS idx_analysis_results_type ON analysis_results(analysis_type);
CREATE INDEX IF NOT EXISTS idx_analysis_results_timestamp ON analysis_results(analysis_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_results_content_hash ON analysis_results(content_hash);
CREATE INDEX IF NOT EXISTS idx_analysis_results_project_scope ON analysis_results(project_id, target_scope);
CREATE INDEX IF NOT EXISTS idx_analysis_results_full_scope ON analysis_results(full_scope);

-- Vector similarity index (only if pgvector is available)
DO $$
DECLARE
    has_pgvector boolean := false;
    has_vector_column boolean := false;
BEGIN
    -- Check if vector extension exists
    SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector') INTO has_pgvector;
    
    -- Check if vector_embedding column exists
    SELECT EXISTS(
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'analysis_results' 
        AND column_name = 'vector_embedding'
    ) INTO has_vector_column;
    
    IF has_pgvector AND has_vector_column THEN
        -- Create vector similarity index
        CREATE INDEX IF NOT EXISTS idx_analysis_results_vector_similarity 
        ON analysis_results USING ivfflat (vector_embedding vector_cosine_ops);
        RAISE NOTICE 'Created vector similarity index';
    END IF;
END $$;

-- Additional indexes
CREATE INDEX IF NOT EXISTS idx_hierarchical_timestamps_scope ON hierarchical_timestamps(scope_path);
CREATE INDEX IF NOT EXISTS idx_hierarchical_timestamps_level ON hierarchical_timestamps(scope_level);
CREATE INDEX IF NOT EXISTS idx_hierarchical_timestamps_change ON hierarchical_timestamps(last_change DESC);

-- Cache indexes
CREATE INDEX IF NOT EXISTS idx_cache_entries_expires ON cache_entries(expires_at);
CREATE INDEX IF NOT EXISTS idx_cache_entries_created ON cache_entries(created_at DESC);

-- Project contexts indexes
CREATE INDEX IF NOT EXISTS idx_project_contexts_active ON project_contexts(is_active);
CREATE INDEX IF NOT EXISTS idx_project_contexts_updated ON project_contexts(updated_at DESC);

-- GIN indexes for JSON and array columns
CREATE INDEX IF NOT EXISTS idx_analysis_result_data_gin ON analysis_results USING gin(result_data);
CREATE INDEX IF NOT EXISTS idx_analysis_source_files_gin ON analysis_results USING gin(source_files);

-- Helper functions
CREATE OR REPLACE FUNCTION update_hierarchical_timestamp(
    p_project_id TEXT,
    p_scope_path TEXT,
    p_scope_level TEXT
) RETURNS void AS $$
BEGIN
    INSERT INTO hierarchical_timestamps (project_id, scope_path, scope_level, last_change, change_count)
    VALUES (p_project_id, p_scope_path, p_scope_level, NOW(), 1)
    ON CONFLICT (project_id, scope_path)
    DO UPDATE SET 
        last_change = NOW(),
        change_count = hierarchical_timestamps.change_count + 1;
END;
$$ LANGUAGE plpgsql;

-- Analysis cleanup function
CREATE OR REPLACE FUNCTION cleanup_stale_analyses(days_old INTEGER DEFAULT 30) 
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM analysis_results 
    WHERE analysis_timestamp < NOW() - INTERVAL '1 day' * days_old;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Insert default project if not exists
INSERT INTO project_contexts (project_id, name, description) 
VALUES ('default', 'Default Project', 'Default project context for knowledge storage')
ON CONFLICT (project_id) DO NOTHING;

-- Function to check schema health
CREATE OR REPLACE FUNCTION check_schema_health() 
RETURNS TABLE(
    component TEXT,
    status TEXT,
    details TEXT
) AS $$
DECLARE
    has_pgvector boolean := false;
    table_count integer;
BEGIN
    -- Check pgvector availability
    SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector') INTO has_pgvector;
    
    -- Check table existence
    SELECT COUNT(*) INTO table_count 
    FROM information_schema.tables 
    WHERE table_name IN ('analysis_results', 'project_contexts', 'hierarchical_timestamps', 'cache_entries');
    
    -- Return status information
    RETURN QUERY SELECT 'pgvector'::TEXT, 
                       CASE WHEN has_pgvector THEN 'AVAILABLE' ELSE 'NOT_AVAILABLE' END,
                       CASE WHEN has_pgvector THEN 'Vector search enabled' ELSE 'Text search only' END;
                       
    RETURN QUERY SELECT 'tables'::TEXT,
                       CASE WHEN table_count = 4 THEN 'OK' ELSE 'INCOMPLETE' END,
                       format('%s/4 tables created', table_count);
END;
$$ LANGUAGE plpgsql;

-- Create a summary view for easy querying
CREATE OR REPLACE VIEW knowledge_summary AS
SELECT 
    project_id,
    analysis_type,
    scope_level,
    COUNT(*) as analysis_count,
    MAX(analysis_timestamp) as latest_analysis,
    MIN(analysis_timestamp) as earliest_analysis
FROM analysis_results
GROUP BY project_id, analysis_type, scope_level
ORDER BY project_id, analysis_type, scope_level;

-- Final setup notification
DO $$
DECLARE
    has_pgvector boolean := false;
    vector_column_exists boolean := false;
BEGIN
    SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector') INTO has_pgvector;
    SELECT EXISTS(
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'analysis_results' 
        AND column_name = 'vector_embedding'
    ) INTO vector_column_exists;
    
    RAISE NOTICE '=== Knowledge Cache Schema Setup Complete ===';
    RAISE NOTICE 'Vector Search: %', CASE WHEN has_pgvector AND vector_column_exists THEN 'ENABLED' ELSE 'DISABLED' END;
    RAISE NOTICE 'pgvector Extension: %', CASE WHEN has_pgvector THEN 'AVAILABLE' ELSE 'NOT AVAILABLE' END;
    RAISE NOTICE 'Text Search: ENABLED';
    RAISE NOTICE 'Project Support: ENABLED';
    RAISE NOTICE '============================================';
END $$; 