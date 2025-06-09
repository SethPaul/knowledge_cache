#!/bin/bash
set -e

# This script runs during PostgreSQL initialization
echo "🔧 Setting up PostgreSQL extensions..."

# Create extensions in the knowledge database
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create required extensions
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS vector;
    
    -- Verify extensions are installed
    SELECT extname, extversion FROM pg_extension WHERE extname IN ('uuid-ossp', 'vector');
EOSQL

echo "✅ PostgreSQL extensions configured successfully" 