#!/bin/bash
set -e

# Codebase Knowledge MCP - Docker Infrastructure Setup
# This script sets up the hybrid Docker Compose + Python MCP architecture

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Codebase Knowledge MCP Setup${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

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

if ! command_exists docker; then
    echo -e "${RED}❌ Docker is not installed. Please install Docker first.${NC}"
    echo -e "${BLUE}   Visit: https://docs.docker.com/get-docker/${NC}"
    exit 1
fi

DOCKER_COMPOSE_CMD=$(check_docker_compose)
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Docker Compose is not available.${NC}"
    echo -e "${BLUE}   Install Docker Compose: https://docs.docker.com/compose/install/${NC}"
    exit 1
fi

if ! command_exists python3; then
    echo -e "${RED}❌ Python 3 is not installed.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Prerequisites satisfied${NC}"
echo ""

# Setup environment
echo -e "${YELLOW}🔧 Setting up environment...${NC}"

if [ ! -f .env ]; then
    cat > .env << 'EOF'
# Database Configuration
POSTGRES_DB=knowledge_reduced
POSTGRES_USER=knowledge_user
POSTGRES_PASSWORD=dev_password_123
DATABASE_URL=postgresql://knowledge_user:dev_password_123@localhost:5432/knowledge_reduced

# Redis Configuration  
REDIS_URL=redis://localhost:6379

# MCP Server Configuration
LOG_LEVEL=INFO
MAX_CONNECTIONS=10

# Development settings
ENVIRONMENT=development
DEBUG=true

# Optional: OpenAI API Key for embeddings
# OPENAI_API_KEY=your_key_here
EOF
    echo -e "${GREEN}✅ Created .env file${NC}"
else
    echo -e "${BLUE}ℹ️  Using existing .env file${NC}"
fi

# Create production environment template
if [ ! -f .env.production ]; then
    cat > .env.production << 'EOF'
# Production Database Configuration
POSTGRES_DB=knowledge_production
POSTGRES_USER=knowledge_prod_user
POSTGRES_PASSWORD=CHANGE_THIS_STRONG_PASSWORD
DATABASE_URL=postgresql://knowledge_prod_user:CHANGE_THIS_STRONG_PASSWORD@localhost:5432/knowledge_production

# Production Redis Configuration
REDIS_URL=redis://localhost:6379

# Production MCP Server Configuration
LOG_LEVEL=WARNING
MAX_CONNECTIONS=50

# Production settings
ENVIRONMENT=production
DEBUG=false

# OpenAI API Key (required for production)
OPENAI_API_KEY=your_production_key_here
EOF
    echo -e "${GREEN}✅ Created .env.production template${NC}"
fi

# Start Docker infrastructure
echo ""
echo -e "${YELLOW}🐳 Starting Docker infrastructure...${NC}"

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
fi

# Check Redis
if $DOCKER_COMPOSE_CMD exec -T redis redis-cli ping >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Redis is ready${NC}"
else
    echo -e "${RED}❌ Redis is not ready${NC}"
    echo -e "${BLUE}   Check logs: $DOCKER_COMPOSE_CMD logs redis${NC}"
fi

# Install Python dependencies
echo ""
echo -e "${YELLOW}🐍 Setting up Python environment...${NC}"

if command_exists pip3; then
    pip3 install -r requirements.txt
    echo -e "${GREEN}✅ Python dependencies installed${NC}"
else
    echo -e "${YELLOW}⚠️  pip3 not found. Please install dependencies manually:${NC}"
    echo -e "${BLUE}   pip install -r requirements.txt${NC}"
fi

# Test database connection
echo ""
echo -e "${YELLOW}🧪 Testing database connection...${NC}"

python3 -c "
import asyncpg
import asyncio
import os

async def test_connection():
    try:
        conn = await asyncpg.connect(os.getenv('DATABASE_URL', 'postgresql://knowledge_user:dev_password_123@localhost:5432/knowledge_reduced'))
        result = await conn.fetchval('SELECT 1')
        await conn.close()
        if result == 1:
            print('✅ Database connection successful')
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
    echo -e "${BLUE}   Check your database configuration in .env${NC}"
fi

# Setup complete
echo ""
echo -e "${GREEN}🎉 Setup complete!${NC}"
echo ""
echo -e "${BLUE}📋 Next Steps:${NC}"
echo ""

echo -e "${YELLOW}1. Configure Claude Desktop:${NC}"
echo -e '   Add this to your claude_desktop_config.json:'
echo -e '   {'
echo -e '     "mcpServers": {'
echo -e '       "knowledge-mcp": {'
echo -e '         "command": "python3",'
echo -e '         "args": ["'$SCRIPT_DIR'/server.py"],'
echo -e '         "env": {'
echo -e '           "DATABASE_URL": "postgresql://knowledge_user:dev_password_123@localhost:5432/knowledge_reduced",'
echo -e '           "REDIS_URL": "redis://localhost:6379"'
echo -e '         }'
echo -e '       }'
echo -e '     }'
echo -e '   }'
echo ""

echo -e "${YELLOW}2. Register your first project:${NC}"
echo -e '   In Claude Desktop, try:'
echo -e '   "Register a new project at /path/to/your/project with ID my-project"'
echo ""

echo -e "${YELLOW}3. Start analyzing code:${NC}"
echo -e '   "Analyze the project structure and create knowledge base"'
echo ""

echo -e "${YELLOW}4. Optional - Start admin tools:${NC}"
echo -e "   $DOCKER_COMPOSE_CMD --profile admin up -d"
echo -e "   pgAdmin: http://localhost:8080 (admin@knowledge.dev / admin123)"
echo -e "   Redis Insight: http://localhost:8001"
echo ""

echo -e "${YELLOW}5. Optional - Start monitoring:${NC}"
echo -e "   $DOCKER_COMPOSE_CMD --profile monitoring up -d"
echo -e "   Prometheus: http://localhost:9090"
echo ""

echo -e "${BLUE}🔧 Management Commands:${NC}"
echo -e "   Start services:  $DOCKER_COMPOSE_CMD up -d"
echo -e "   Stop services:   $DOCKER_COMPOSE_CMD down"
echo -e "   View logs:       $DOCKER_COMPOSE_CMD logs -f"
echo -e "   Check status:    $DOCKER_COMPOSE_CMD ps"
echo ""

echo -e "${BLUE}📚 Documentation:${NC}"
echo -e "   Architecture:    ./DOCKER_ARCHITECTURE.md"
echo -e "   Implementation:  ./IMPLEMENTATION_PLAN.md"
echo -e "   Lifecycle:       ./LIFECYCLE_MANAGEMENT.md"
echo ""

echo -e "${GREEN}Happy coding with AI-powered codebase intelligence! 🤖✨${NC}" 