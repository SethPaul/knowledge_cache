"""
Simple environment-based configuration for reduced scope MCP server.

Follows single-source-of-truth principle with sensible defaults.
"""

import os
from typing import Optional


class Config:
    """Environment-based configuration with production-ready defaults."""
    
    # Database Configuration
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql://knowledge_user:dev_password_123@localhost:5432/knowledge_reduced"
    )
    
    # Redis Configuration
    REDIS_URL: str = os.getenv(
        "REDIS_URL", 
        "redis://localhost:6379/0"
    )
    
    # Logging Configuration
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    MCP_DEBUG: bool = os.getenv("MCP_DEBUG", "false").lower() == "true"
    
    # Performance Tuning
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "10"))
    DB_POOL_MAX_OVERFLOW: int = int(os.getenv("DB_POOL_MAX_OVERFLOW", "20"))
    
    # Cache Configuration
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "300"))  # 5 minutes
    CACHE_MAX_SIZE: int = int(os.getenv("CACHE_MAX_SIZE", "1000"))
    
    # Search Configuration
    SEARCH_DEFAULT_LIMIT: int = int(os.getenv("SEARCH_DEFAULT_LIMIT", "10"))
    SEARCH_MAX_LIMIT: int = int(os.getenv("SEARCH_MAX_LIMIT", "100"))
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    
    # Freshness Thresholds (in seconds)
    FRESHNESS_FRESH_THRESHOLD: int = int(os.getenv("FRESHNESS_FRESH_THRESHOLD", "3600"))     # 1 hour
    FRESHNESS_RECENT_THRESHOLD: int = int(os.getenv("FRESHNESS_RECENT_THRESHOLD", "86400"))  # 1 day  
    FRESHNESS_STALE_THRESHOLD: int = int(os.getenv("FRESHNESS_STALE_THRESHOLD", "604800"))   # 1 week
    
    # Tool Response Configuration
    TOOL_TIMEOUT_SECONDS: float = float(os.getenv("TOOL_TIMEOUT_SECONDS", "30.0"))
    INCLUDE_PERFORMANCE_METRICS: bool = os.getenv("INCLUDE_PERFORMANCE_METRICS", "true").lower() == "true"
    
    @classmethod
    def validate(cls) -> bool:
        """Validate configuration values."""
        try:
            # Check required environment variables have reasonable values
            assert cls.DB_POOL_SIZE > 0
            assert cls.CACHE_TTL_SECONDS > 0
            assert cls.SEARCH_DEFAULT_LIMIT > 0
            assert cls.TOOL_TIMEOUT_SECONDS > 0
            
            # Check thresholds are in ascending order
            assert cls.FRESHNESS_FRESH_THRESHOLD < cls.FRESHNESS_RECENT_THRESHOLD
            assert cls.FRESHNESS_RECENT_THRESHOLD < cls.FRESHNESS_STALE_THRESHOLD
            
            return True
        except AssertionError:
            return False
    
    @classmethod
    def get_database_config(cls) -> dict:
        """Get database connection configuration."""
        return {
            "dsn": cls.DATABASE_URL,
            "min_size": 1,
            "max_size": cls.DB_POOL_SIZE,
            "max_inactive_connection_lifetime": 300,
            "command_timeout": cls.TOOL_TIMEOUT_SECONDS
        }
    
    @classmethod
    def get_redis_config(cls) -> dict:
        """Get Redis connection configuration."""
        return {
            "url": cls.REDIS_URL,
            "socket_timeout": 5.0,
            "socket_connect_timeout": 5.0,
            "retry_on_timeout": True
        }
    
    @classmethod
    def get_cache_config(cls) -> dict:
        """Get cache configuration."""
        return {
            "ttl_seconds": cls.CACHE_TTL_SECONDS,
            "max_size": cls.CACHE_MAX_SIZE
        }
    
    @classmethod
    def get_freshness_config(cls) -> dict:
        """Get freshness threshold configuration."""
        return {
            "fresh_threshold": cls.FRESHNESS_FRESH_THRESHOLD,
            "recent_threshold": cls.FRESHNESS_RECENT_THRESHOLD,
            "stale_threshold": cls.FRESHNESS_STALE_THRESHOLD
        }


# Validate configuration on import
if not Config.validate():
    raise ValueError(
        "Invalid configuration detected. Please check environment variables."
    ) 