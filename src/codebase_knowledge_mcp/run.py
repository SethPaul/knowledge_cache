#!/usr/bin/env python3
"""
Simple entry point for the Reduced Scope MCP Server.

Usage:
    python run.py
    
Environment variables:
    DATABASE_URL - PostgreSQL connection string
    REDIS_URL - Redis connection string  
    LOG_LEVEL - Logging level (DEBUG, INFO, WARN, ERROR)
"""

import asyncio
import os
import sys
from pathlib import Path

# Add the current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from server import main

if __name__ == "__main__":
    # Simple startup info (non-structured for user-friendly display)
    print("🚀 Starting Codebase Knowledge MCP Server...")
    print("💡 Make sure PostgreSQL and Redis are running")
    print("📋 Check docker-compose.yml for infrastructure setup")
    print()
    
    # Check if we're in a virtual environment (but don't require it for production)
    in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    if not in_venv:
        print("ℹ️  Running outside virtual environment")
        print("   (For development: source .venv/bin/activate)")
    
    # Show environment configuration
    if not os.getenv('DATABASE_URL'):
        print("ℹ️  Using default DATABASE_URL (postgresql://knowledge_user:dev_password_123@localhost:5432/knowledge_reduced)")
    if not os.getenv('REDIS_URL'):
        print("ℹ️  Using default REDIS_URL (redis://localhost:6379/0)")
    
    log_level = os.getenv('LOG_LEVEL', 'INFO')
    print(f"ℹ️  Log level: {log_level}")
    print()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✅ Server stopped by user")
    except Exception as e:
        print(f"\n❌ Server failed to start: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main_entry():
    """Synchronous entry point for uvx/pip."""
    import os
    import sys
    
    # Ensure we have the right Python path
    current_dir = str(Path(__file__).parent)
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    
    print("🚀 Starting Reduced Scope MCP Server...")
    print("💡 Make sure PostgreSQL and Redis are running")
    print("📋 Check docker-compose.yml for infrastructure setup")
    print()
    
    # Check environment variables
    if not os.getenv('DATABASE_URL'):
        print("ℹ️  Using default DATABASE_URL")
    if not os.getenv('REDIS_URL'):
        print("ℹ️  Using default REDIS_URL")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✅ Server stopped by user")
    except Exception as e:
        print(f"\n❌ Server failed to start: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1) 