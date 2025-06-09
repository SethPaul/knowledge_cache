# Codebase Knowledge MCP Server

A **focused, production-ready MCP server** that provides exactly **5 core tools** for AI agents working with codebase knowledge. Built from the learnings of a full-scope implementation, this version trades complexity for **reliability, performance, and maintainability**.

## 🎯 Overview

This MCP server solves the "M×N integration problem" for codebase intelligence by providing a unified interface for AI agents to store, search, and manage code knowledge with transparent freshness tracking.

## 🔧 The 5 Core Tools

1. **`search_project_knowledge`** - Semantic search across all project knowledge
2. **`get_cached_analysis_with_freshness`** - Retrieve analysis with transparent staleness information  
3. **`get_component_architecture`** - Deep component understanding and relationships
4. **`store_analysis_result`** - Store knowledge with hierarchical distribution
5. **`manage_knowledge_lifecycle`** - Archive, remove, and cleanup stale knowledge

## ✨ Key Design Principles

- **Simplicity Over Complexity**: Single component vs 5 separate components
- **Agent-Centric Design**: Transparent freshness, actionable recommendations
- **Performance First**: Hierarchical organization, content addressing, multi-level caching
- **Production Ready**: Structured logging, health monitoring, graceful error handling

## 🚀 Quick Start

### Automated Setup (Recommended)

The easiest way to get started is using our automated setup script that handles everything:

```bash
# 1. Clone the repository
git clone <repository>
cd knowledge_cache

# 2. Run the automated setup
chmod +x setup.sh
./setup.sh

# 3. (Optional) Verify the setup
./test_setup.sh
```

**What the setup script does:**
- 🐳 Builds custom PostgreSQL Docker image with pgvector pre-installed
- 🚀 Starts PostgreSQL and Redis containers
- 🐍 Creates virtual environment and installs dependencies
- 📦 Builds and installs the MCP package
- 🗄️ Initializes database schema with adaptive pgvector support
- 🧪 Tests the complete installation

### Manual Setup

If you prefer manual setup or need custom configuration:

#### Prerequisites
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager (modern Python package management)
- Docker and Docker Compose
- PostgreSQL client tools (for manual schema setup)

#### Steps
```bash
# 1. Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# 2. Create virtual environment and install dependencies
uv venv
uv pip install -r requirements.txt

# 3. Set up environment (optional - has defaults)
export DATABASE_URL="postgresql://knowledge_user:dev_password_123@localhost:5432/knowledge_reduced"
export REDIS_URL="redis://localhost:6379/0"

# 4. Start infrastructure
docker-compose up -d

# 5. Initialize database
PGPASSWORD=dev_password_123 psql -h localhost -U knowledge_user -d knowledge_reduced -f src/codebase_knowledge_mcp/schema.sql

# 6. Run server
uv run python src/codebase_knowledge_mcp/run.py
```

### Alternative: Run via uvx (for installed package)
```bash
# Build and install package
uv build
uvx --from dist/codebase_knowledge_mcp-*.whl codebase-knowledge-mcp
```

### MCP Integration

#### Option 1: Direct Python execution
Add to your MCP client configuration (e.g., Claude Desktop):

```json
{
  "mcpServers": {
    "codebase-knowledge": {
      "command": "uv",
      "args": ["run", "python", "/path/to/codebase_knowledge_mcp/src/codebase_knowledge_mcp/run.py"],
      "cwd": "/path/to/codebase_knowledge_mcp",
      "env": {
        "DATABASE_URL": "postgresql://knowledge_user:dev_password_123@localhost:5432/knowledge_reduced",
        "REDIS_URL": "redis://localhost:6379/0"
      }
    }
  }
}
```

#### Option 2: Installed package via uvx
```json
{
  "mcpServers": {
    "codebase-knowledge": {
      "command": "uvx",
      "args": [
        "--from", 
        "/path/to/codebase_knowledge_mcp/dist/codebase_knowledge_mcp-0.1.6-py3-none-any.whl",
        "codebase-knowledge-mcp"
      ],
      "env": {
        "DATABASE_URL": "postgresql://knowledge_user:dev_password_123@localhost:5432/knowledge_reduced",
        "REDIS_URL": "redis://localhost:6379/0"
      }
    }
  }
}
```

## 📊 Architecture

### Overall System Architecture
```
┌─────────────────────────────────────────────────────────────┐
│                     AI Agents                              │
│          (Cursor, Claude Desktop, Windsurf)                │
└─────────────────────┬───────────────────────────────────────┘
                      │ MCP stdio Protocol
┌─────────────────────▼───────────────────────────────────────┐
│                  MCP Server                                 │
│              (5 Core Tools Only)                          │
├─────────────────────┬───────────────────────────────────────┤
│               Knowledge Store                               │
│        (Unified CRUD + Freshness + Search)                │
├─────────────────────┼───────────────────────────────────────┤
│     Redis Cache     │         PostgreSQL + pgvector        │
│   (Hot Data L2)     │      (Cold Storage + Vector Search)  │
└─────────────────────┴───────────────────────────────────────┘
```

### Docker Infrastructure
The setup uses a custom Docker architecture for reliable pgvector support:

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose                          │
├─────────────────────┬───────────────────────────────────────┤
│  Custom PostgreSQL  │              Redis Cache             │
│     Container        │              Container              │
│                     │                                     │
│ • pgvector/pg16 base│ • redis:7-alpine                   │
│ • pgvector pre-      │ • Persistent storage               │
│   installed         │ • LRU eviction policy              │
│ • Auto extension    │ • Health monitoring                │
│   setup             │                                     │
│ • Schema init       │                                     │
│   scripts           │                                     │
└─────────────────────┴───────────────────────────────────────┘
```

**Key improvements in Docker setup:**
- **Custom PostgreSQL image**: Built with pgvector extension pre-installed
- **Automated initialization**: Extensions and schema created automatically
- **No manual intervention**: Complete setup with single command
- **Adaptive schema**: Automatically detects and configures pgvector capabilities

## 🔍 Logging and Observability

### Structured Logging
The server uses structured JSON logging for production observability:

```json
{"version": "0.1.6", "python_version": "3.12.3", "event": "Starting Codebase Knowledge MCP Server", "logger": "codebase_knowledge_mcp", "level": "info", "timestamp": "2025-06-09T13:09:46.074873Z"}
{"database_url": "postgresql://...", "event": "Connecting to PostgreSQL", "logger": "codebase_knowledge_mcp", "level": "info", "timestamp": "2025-06-09T13:09:46.075075Z"}
{"total_analyses": 19, "cache_hit_rate": 0.257, "event": "Health check passed", "logger": "codebase_knowledge_mcp", "level": "info", "timestamp": "2025-06-09T13:09:47.629331Z"}
```

### Environment Variables for Logging
- **`LOG_LEVEL`**: Application log level (DEBUG, INFO, WARNING, ERROR) - default: INFO
- **`MCP_DEBUG`**: Enable detailed MCP framework logging (true/false) - default: false

### Troubleshooting
**Reduce log noise**: Set `LOG_LEVEL=WARNING` to only show warnings and errors
**Enable MCP debugging**: Set `MCP_DEBUG=true` to see detailed MCP protocol messages
**Debug mode**: Set `LOG_LEVEL=DEBUG` for full diagnostic output with human-readable console formatting

Example debug configuration:
```bash
export LOG_LEVEL=DEBUG
export MCP_DEBUG=true
uv run python src/codebase_knowledge_mcp/run.py
```

## 📈 Performance Targets

- **Cached Operations**: P95 < 100ms  
- **Vector Search**: P95 < 500ms
- **Storage Operations**: P95 < 300ms
- **Freshness Checks**: P95 < 50ms

## 📋 Documentation

- **[Usage Guide](USAGE_GUIDE.md)** - Detailed tool usage examples
- **[Implementation Plan](IMPLEMENTATION_PLAN.md)** - Technical architecture details
- **[Lifecycle Management](LIFECYCLE_MANAGEMENT.md)** - Knowledge cleanup strategies
- **[MCP Ecosystem Analysis](MCP_ECOSYSTEM_ANALYSIS.md)** - Integration patterns

## 🛠 Development

```bash
# Create development environment
uv venv
uv pip install -r requirements.txt

# Install development dependencies
uv pip install pytest pytest-asyncio black ruff

# Format code
uv run black src/
uv run ruff check src/

# Run tests
uv run pytest

# Run with development logging
LOG_LEVEL=DEBUG uv run python src/codebase_knowledge_mcp/run.py

# Build package
uv build
```

### Why uv?
**Important**: This project requires `uv` for proper dependency management. Using `pip` directly can cause dependency conflicts and runtime issues. `uv` provides:
- Faster dependency resolution
- Reliable virtual environment management
- Better dependency isolation
- Consistent builds across environments

## License

MIT License - see LICENSE file for details. 