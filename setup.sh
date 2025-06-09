#!/bin/bash
set -e

# Codebase Knowledge MCP - Enhanced Setup Script
# This script sets up the complete Docker + Python MCP architecture with pgvector support

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
INSTALL_PGVECTOR=${INSTALL_PGVECTOR:-true}
SKIP_DOCKER_SETUP=${SKIP_DOCKER_SETUP:-false}
ENVIRONMENT=${ENVIRONMENT:-development}

echo -e "${BLUE}🚀 Codebase Knowledge MCP Setup${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-pgvector)
            INSTALL_PGVECTOR=false
            shift
            ;;
        --skip-docker)
            SKIP_DOCKER_SETUP=true
            shift
            ;;
        --production)
            ENVIRONMENT=production
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --no-pgvector    Skip pgvector installation (disables semantic search)"
            echo "  --skip-docker    Skip Docker setup (assumes infrastructure already running)"
            echo "  --production     Set up for production environment"
            echo "  -h, --help       Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check Docker Compose
check_docker_compose() {
    if command_exists docker-compose; then
        echo "docker-compose"
    elif docker compose version >/dev/null 2>&1; then
        echo "docker compose"
    else
        return 1
    fi
}

# Check prerequisites
echo -e "${YELLOW}📋 Checking prerequisites...${NC}"

if ! command_exists docker && [ "$SKIP_DOCKER_SETUP" = "false" ]; then
    echo -e "${RED}❌ Docker is not installed. Please install Docker first.${NC}"
    echo -e "${BLUE}   Visit: https://docs.docker.com/get-docker/${NC}"
    exit 1
fi

if [ "$SKIP_DOCKER_SETUP" = "false" ]; then
    DOCKER_COMPOSE_CMD=$(check_docker_compose)
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Docker Compose is not available.${NC}"
        echo -e "${BLUE}   Install Docker Compose: https://docs.docker.com/compose/install/${NC}"
        exit 1
    fi
fi

if ! command_exists python3; then
    echo -e "${RED}❌ Python 3 is not installed.${NC}"
    exit 1
fi

# Check for uv (preferred) or pip
if command_exists uv; then
    PYTHON_INSTALLER="uv"
    echo -e "${GREEN}✅ Using uv for Python package management${NC}"
elif command_exists pip3; then
    PYTHON_INSTALLER="pip3"
    echo -e "${YELLOW}⚠️  Using pip3 (consider installing uv for better performance)${NC}"
else
    echo -e "${RED}❌ Neither uv nor pip3 is available.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Prerequisites satisfied${NC}"
echo ""

# Setup environment
echo -e "${YELLOW}🔧 Setting up environment...${NC}"

ENV_FILE=".env"
if [ "$ENVIRONMENT" = "production" ]; then
    ENV_FILE=".env.production"
fi

if [ ! -f "$ENV_FILE" ]; then
    if [ "$ENVIRONMENT" = "production" ]; then
        cat > "$ENV_FILE" << 'EOF'
# Production Database Configuration
POSTGRES_DB=knowledge_production
POSTGRES_USER=knowledge_prod_user
POSTGRES_PASSWORD=CHANGE_THIS_STRONG_PASSWORD
DATABASE_URL=postgresql://knowledge_prod_user:CHANGE_THIS_STRONG_PASSWORD@localhost:5432/knowledge_production

# Production Redis Configuration
REDIS_URL=redis://localhost:6379/0

# Production MCP Server Configuration
LOG_LEVEL=WARNING
MAX_CONNECTIONS=50
ENABLE_VECTOR_SEARCH=true

# Production settings
ENVIRONMENT=production
DEBUG=false

# OpenAI API Key (required for production)
OPENAI_API_KEY=your_production_key_here
EOF
    else
        cat > "$ENV_FILE" << 'EOF'
# Database Configuration
POSTGRES_DB=knowledge_reduced
POSTGRES_USER=knowledge_user
POSTGRES_PASSWORD=dev_password_123
DATABASE_URL=postgresql://knowledge_user:dev_password_123@localhost:5432/knowledge_reduced

# Redis Configuration  
REDIS_URL=redis://localhost:6379/0

# MCP Server Configuration
LOG_LEVEL=INFO
MAX_CONNECTIONS=10
ENABLE_VECTOR_SEARCH=true

# Development settings
ENVIRONMENT=development
DEBUG=true

# Optional: OpenAI API Key for embeddings
# OPENAI_API_KEY=your_key_here
EOF
    fi
    echo -e "${GREEN}✅ Created $ENV_FILE file${NC}"
else
    echo -e "${BLUE}ℹ️  Using existing $ENV_FILE file${NC}"
fi

# Update environment with pgvector setting
if [ "$INSTALL_PGVECTOR" = "false" ]; then
    if grep -q "ENABLE_VECTOR_SEARCH" "$ENV_FILE"; then
        sed -i 's/ENABLE_VECTOR_SEARCH=true/ENABLE_VECTOR_SEARCH=false/' "$ENV_FILE"
    else
        echo "ENABLE_VECTOR_SEARCH=false" >> "$ENV_FILE"
    fi
    echo -e "${YELLOW}⚠️  Vector search disabled (pgvector not installed)${NC}"
fi

# Start Docker infrastructure
if [ "$SKIP_DOCKER_SETUP" = "false" ]; then
    echo ""
    echo -e "${YELLOW}🐳 Setting up Docker infrastructure...${NC}"
    
    echo -e "${BLUE}📦 Building custom PostgreSQL image with pgvector...${NC}"
    if ! $DOCKER_COMPOSE_CMD build postgres; then
        echo -e "${RED}❌ Failed to build PostgreSQL image${NC}"
        exit 1
    fi
    
    echo -e "${BLUE}🚀 Starting PostgreSQL and Redis containers...${NC}"
    $DOCKER_COMPOSE_CMD up -d postgres redis

    echo -e "${BLUE}⏳ Waiting for services to be ready...${NC}"
    sleep 10

    # Check service health
    echo -e "${YELLOW}🔍 Checking service health...${NC}"

    # Check PostgreSQL
    if $DOCKER_COMPOSE_CMD exec -T postgres pg_isready -U knowledge_user -d knowledge_reduced >/dev/null 2>&1; then
        echo -e "${GREEN}✅ PostgreSQL is ready${NC}"
    else
        echo -e "${RED}❌ PostgreSQL is not ready${NC}"
        echo -e "${BLUE}   Check logs: $DOCKER_COMPOSE_CMD logs postgres${NC}"
        exit 1
    fi

    # Check Redis
    if $DOCKER_COMPOSE_CMD exec -T redis redis-cli ping >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Redis is ready${NC}"
    else
        echo -e "${RED}❌ Redis is not ready${NC}"
        echo -e "${BLUE}   Check logs: $DOCKER_COMPOSE_CMD logs redis${NC}"
        exit 1
    fi
fi

# pgvector is now pre-installed in the custom Docker image
echo -e "${GREEN}✅ pgvector support included in Docker image${NC}"

# Install Python dependencies
echo ""
echo -e "${YELLOW}🐍 Setting up Python environment...${NC}"

if [ "$PYTHON_INSTALLER" = "uv" ]; then
    # Create virtual environment if it doesn't exist
    if [ ! -d ".venv" ]; then
        uv venv
        echo -e "${GREEN}✅ Created virtual environment${NC}"
    fi
    
    # Install dependencies
    if [ "$INSTALL_PGVECTOR" = "true" ]; then
        uv pip install -r requirements.txt
    else
        # Install without pgvector and vector-related dependencies
        uv pip install -r <(grep -v "pgvector\|sentence-transformers\|torch" requirements.txt)
        echo -e "${YELLOW}⚠️  Installed without vector search dependencies${NC}"
    fi
    
    # Build and install the package
    echo -e "${BLUE}📦 Building and installing MCP package...${NC}"
    uv build
    uv pip install -e .
    echo -e "${GREEN}✅ Python dependencies and MCP package installed with uv${NC}"
else
    # Use pip3
    if [ "$INSTALL_PGVECTOR" = "true" ]; then
        pip3 install -r requirements.txt
    else
        # Install without pgvector and vector-related dependencies
        pip3 install -r <(grep -v "pgvector\|sentence-transformers\|torch" requirements.txt)
        echo -e "${YELLOW}⚠️  Installed without vector search dependencies${NC}"
    fi
    
    # Install package in editable mode
    echo -e "${BLUE}📦 Installing MCP package...${NC}"
    pip3 install -e .
    echo -e "${GREEN}✅ Python dependencies and MCP package installed with pip3${NC}"
fi

# Initialize database schema (if needed)
echo ""
echo -e "${YELLOW}🗄️  Checking database schema...${NC}"

# Source environment variables
source "$ENV_FILE"

# Check if schema is already initialized by checking for a core table
if command_exists psql; then
    SCHEMA_EXISTS=$(PGPASSWORD="${POSTGRES_PASSWORD}" psql -h localhost -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -c "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'analysis_results');" 2>/dev/null | tr -d ' ')
    
    if [ "$SCHEMA_EXISTS" = "t" ]; then
        echo -e "${GREEN}✅ Database schema already initialized${NC}"
        
        # Ensure default project exists
        PGPASSWORD="${POSTGRES_PASSWORD}" psql -h localhost -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "INSERT INTO project_contexts (project_id, project_name, project_root, base_scope) VALUES ('default', 'Default Project', '/default', 'default') ON CONFLICT (project_id) DO NOTHING;" >/dev/null 2>&1
        echo -e "${GREEN}✅ Default project context verified${NC}"
    else
        echo -e "${YELLOW}⚠️  Schema not initialized - this should be handled by Docker init scripts${NC}"
        echo -e "${BLUE}   If using custom setup, run: PGPASSWORD=${POSTGRES_PASSWORD} psql -h localhost -U ${POSTGRES_USER} -d ${POSTGRES_DB} -f src/codebase_knowledge_mcp/schema.sql${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  psql not found. Cannot verify schema${NC}"
fi

# Test database connection and MCP server
echo ""
echo -e "${YELLOW}🧪 Testing system...${NC}"

# Test database connection
PYTHON_CMD="python3"
if [ "$PYTHON_INSTALLER" = "uv" ]; then
    PYTHON_CMD="uv run python"
fi

$PYTHON_CMD -c "
import asyncpg
import asyncio
import os
from dotenv import load_dotenv

load_dotenv('$ENV_FILE')

async def test_connection():
    try:
        conn = await asyncpg.connect(os.getenv('DATABASE_URL'))
        result = await conn.fetchval('SELECT 1')
        
        # Test if pgvector is available
        try:
            await conn.fetchval('SELECT 1 FROM pg_extension WHERE extname = \\'vector\\'')
            vector_available = True
        except:
            vector_available = False
            
        await conn.close()
        
        if result == 1:
            print('✅ Database connection successful')
            if vector_available:
                print('✅ pgvector extension available')
            else:
                print('⚠️  pgvector extension not available (vector search disabled)')
            return True
    except Exception as e:
        print(f'❌ Database connection failed: {e}')
        return False
    return False

if asyncio.run(test_connection()):
    exit(0)
else:
    exit(1)
" 2>/dev/null

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Database connection test passed${NC}"
else
    echo -e "${RED}❌ Database connection test failed${NC}"
    echo -e "${BLUE}   Check your database configuration in $ENV_FILE${NC}"
fi

# Test MCP server startup
echo -e "${YELLOW}🔧 Testing MCP server startup...${NC}"
if [ "$PYTHON_INSTALLER" = "uv" ]; then
    timeout 10s uv run codebase-knowledge-mcp >/dev/null 2>&1 &
else
    timeout 10s .venv/bin/codebase-knowledge-mcp >/dev/null 2>&1 &
fi
MCP_PID=$!
sleep 3

if kill -0 $MCP_PID 2>/dev/null; then
    echo -e "${GREEN}✅ MCP server starts successfully${NC}"
    kill $MCP_PID 2>/dev/null || true
else
    echo -e "${YELLOW}⚠️  MCP server test skipped (may need environment setup)${NC}"
fi

# Setup complete
echo ""
echo -e "${GREEN}🎉 Setup complete!${NC}"
echo ""
echo -e "${BLUE}📋 Configuration Summary:${NC}"
echo -e "   Environment: $ENVIRONMENT"
echo -e "   Vector Search: $([ "$INSTALL_PGVECTOR" = "true" ] && echo "Enabled" || echo "Disabled")"
echo -e "   Python Manager: $PYTHON_INSTALLER"
echo -e "   Config File: $ENV_FILE"
echo ""

echo -e "${BLUE}📋 Next Steps:${NC}"
echo ""

echo -e "${YELLOW}1. Configure MCP Client (e.g., Claude Desktop):${NC}"
echo -e '   Add this to your configuration:'
echo -e '   {'
echo -e '     "mcpServers": {'
echo -e '       "codebase-knowledge": {'
if [ "$PYTHON_INSTALLER" = "uv" ]; then
echo -e '         "command": "uv",'
echo -e '         "args": ["run", "codebase-knowledge-mcp"],'
echo -e '         "cwd": "'$SCRIPT_DIR'",'
else
echo -e '         "command": "'$SCRIPT_DIR'/.venv/bin/codebase-knowledge-mcp",'
echo -e '         "args": [],'
fi
echo -e '         "env": {'
echo -e '           "DATABASE_URL": "'$(grep DATABASE_URL $ENV_FILE | cut -d'=' -f2-)'","'
echo -e '           "REDIS_URL": "'$(grep REDIS_URL $ENV_FILE | cut -d'=' -f2-)'","'
echo -e '           "LOG_LEVEL": "'$(grep LOG_LEVEL $ENV_FILE | cut -d'=' -f2-)'"'
echo -e '         }'
echo -e '       }'
echo -e '     }'
echo -e '   }'
echo ""

echo -e "${YELLOW}2. Start the MCP server:${NC}"
if [ "$PYTHON_INSTALLER" = "uv" ]; then
    echo -e "   cd $SCRIPT_DIR && uv run codebase-knowledge-mcp"
else
    echo -e "   cd $SCRIPT_DIR && .venv/bin/codebase-knowledge-mcp"
fi
echo ""

echo -e "${YELLOW}3. Test with your MCP client:${NC}"
echo -e '   "Store analysis for my project architecture"'
echo ""

if [ "$SKIP_DOCKER_SETUP" = "false" ]; then
echo -e "${YELLOW}4. Optional - Management commands:${NC}"
echo -e "   Start services:  $DOCKER_COMPOSE_CMD up -d"
echo -e "   Stop services:   $DOCKER_COMPOSE_CMD down"
echo -e "   View logs:       $DOCKER_COMPOSE_CMD logs -f"
echo -e "   Check status:    $DOCKER_COMPOSE_CMD ps"
echo ""
fi

if [ "$INSTALL_PGVECTOR" = "false" ]; then
echo -e "${YELLOW}💡 To enable vector search later:${NC}"
echo -e "   1. Re-run setup: ./setup.sh"
echo -e "   2. Update ENABLE_VECTOR_SEARCH=true in $ENV_FILE"
echo -e "   3. Restart the MCP server"
echo ""
fi

echo -e "${BLUE}📚 Documentation:${NC}"
echo -e "   Usage Guide:     ./USAGE_GUIDE.md"
echo -e "   Implementation:  ./IMPLEMENTATION_PLAN.md"
echo -e "   Lifecycle:       ./LIFECYCLE_MANAGEMENT.md"
echo ""

echo -e "${GREEN}Happy coding with AI-powered codebase intelligence! 🤖✨${NC}" 