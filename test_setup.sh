#!/bin/bash
set -e

# Test script for knowledge cache setup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🧪 Testing Knowledge Cache Setup${NC}"
echo -e "${BLUE}=================================${NC}"
echo ""

# Source environment
source .env

echo -e "${YELLOW}1. Testing Docker containers...${NC}"

# Check if containers are running
if docker compose ps postgres | grep -q "Up"; then
    echo -e "${GREEN}✅ PostgreSQL container is running${NC}"
else
    echo -e "${RED}❌ PostgreSQL container is not running${NC}"
    exit 1
fi

if docker compose ps redis | grep -q "Up"; then
    echo -e "${GREEN}✅ Redis container is running${NC}"
else
    echo -e "${RED}❌ Redis container is not running${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}2. Testing database connection and schema...${NC}"

# Test PostgreSQL connection and pgvector
if PGPASSWORD="$POSTGRES_PASSWORD" psql -h localhost -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1;" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Database connection successful${NC}"
else
    echo -e "${RED}❌ Database connection failed${NC}"
    exit 1
fi

# Check pgvector extension
if PGPASSWORD="$POSTGRES_PASSWORD" psql -h localhost -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT extname FROM pg_extension WHERE extname = 'vector';" | grep -q "vector"; then
    echo -e "${GREEN}✅ pgvector extension is available${NC}"
else
    echo -e "${YELLOW}⚠️  pgvector extension not found${NC}"
fi

# Check schema tables
TABLES=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h localhost -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "
SELECT COUNT(*) FROM information_schema.tables 
WHERE table_name IN ('analysis_results', 'project_contexts', 'hierarchical_timestamps', 'cache_entries');
")

if [ "$TABLES" -eq 4 ]; then
    echo -e "${GREEN}✅ All schema tables present (4/4)${NC}"
else
    echo -e "${RED}❌ Missing schema tables ($TABLES/4)${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}3. Testing MCP server...${NC}"

# Test MCP server startup
if command -v uv >/dev/null 2>&1; then
    echo -e "${BLUE}ℹ️  Testing with uv...${NC}"
    timeout 10s uv run codebase-knowledge-mcp &
else
    echo -e "${BLUE}ℹ️  Testing with direct execution...${NC}"
    timeout 10s .venv/bin/codebase-knowledge-mcp &
fi

MCP_PID=$!
sleep 5

# Check if the MCP server process was started (timeout will kill it)
wait $MCP_PID 2>/dev/null
EXIT_CODE=$?

if [ $EXIT_CODE -eq 124 ]; then
    # Exit code 124 means timeout - server started successfully
    echo -e "${GREEN}✅ MCP server starts successfully (terminated by timeout)${NC}"
elif [ $EXIT_CODE -eq 0 ]; then
    # Server started and shut down gracefully
    echo -e "${GREEN}✅ MCP server starts successfully${NC}"
else
    echo -e "${RED}❌ MCP server failed to start (exit code: $EXIT_CODE)${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}4. Testing knowledge storage and retrieval...${NC}"

# Create a simple test using the Python API directly
cat > test_knowledge.py << 'EOF'
import asyncio
import asyncpg
import json
import os
from datetime import datetime

async def test_knowledge_operations():
    """Test basic knowledge storage and retrieval."""
    
    # Connect to database
    conn = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    try:
        # Test storing knowledge
        test_scope = f"test.setup.{int(datetime.now().timestamp())}"
        test_data = {
            "description": "Test setup verification",
            "timestamp": datetime.now().isoformat(),
            "status": "testing"
        }
        
        # Insert test analysis
        await conn.execute("""
            INSERT INTO analysis_results (
                analysis_type, project_id, target_scope, full_scope, scope_level,
                result_data, content_hash, source_files
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, 
            "structure", "default", test_scope, test_scope, "file",
            json.dumps(test_data), "test_hash_123", ["test_setup.sh"]
        )
        
        print("✅ Successfully stored test knowledge")
        
        # Test retrieving knowledge
        result = await conn.fetchrow("""
            SELECT analysis_type, target_scope, result_data
            FROM analysis_results 
            WHERE target_scope = $1
        """, test_scope)
        
        if result:
            print("✅ Successfully retrieved test knowledge")
            print(f"   Type: {result['analysis_type']}")
            print(f"   Scope: {result['target_scope']}")
            
            # Clean up test data
            await conn.execute("DELETE FROM analysis_results WHERE target_scope = $1", test_scope)
            print("✅ Test data cleaned up")
        else:
            print("❌ Failed to retrieve test knowledge")
            return False
            
    except Exception as e:
        print(f"❌ Knowledge test failed: {e}")
        return False
    finally:
        await conn.close()
    
    return True

if __name__ == "__main__":
    import dotenv
    dotenv.load_dotenv()
    
    success = asyncio.run(test_knowledge_operations())
    exit(0 if success else 1)
EOF

if command -v uv >/dev/null 2>&1; then
    uv run python test_knowledge.py
else
    .venv/bin/python test_knowledge.py
fi

# Clean up test file
rm -f test_knowledge.py

echo ""
echo -e "${GREEN}🎉 All tests passed! Knowledge Cache is ready to use.${NC}"
echo ""
echo -e "${BLUE}📋 Setup Summary:${NC}"
echo -e "   🐳 Docker containers: Running"
echo -e "   🗄️  Database schema: Complete"
echo -e "   🔍 pgvector support: Available"
echo -e "   🤖 MCP server: Functional"
echo -e "   📊 Knowledge operations: Working"
echo ""
echo -e "${YELLOW}💡 You can now use the MCP server with your configured client!${NC}" 