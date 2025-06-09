#!/usr/bin/env python3
"""
Reduced Scope MCP Server for Codebase Knowledge.

High-performance, production-ready MCP server with 5 core tools.
Based on learnings from the full-scope implementation.
"""

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional

import asyncpg
import redis.asyncio as redis
import structlog
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Resource, Tool, TextContent, EmbeddedResource

from config import Config
from knowledge_store import KnowledgeStore
from models import (
    AnalysisType,
    LifecycleAction,
    LifecycleRequest,
    ScopeLevel,
    StorageRequest
)


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer() if Config.LOG_LEVEL.upper() == "DEBUG" else structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

# Set standard library logging level
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL.upper()),
    format='%(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)

# Configure MCP framework logging to reduce noise
# Set MCP framework level based on configuration
mcp_level = logging.DEBUG if Config.MCP_DEBUG else logging.WARNING
mcp_loggers = [
    "mcp",
    "mcp.server", 
    "mcp.server.lowlevel",
    "mcp.server.lowlevel.server",
    "mcp.server.stdio"
]

for logger_name in mcp_loggers:
    framework_logger = logging.getLogger(logger_name)
    framework_logger.setLevel(mcp_level)

# Configure third-party library loggers to reduce noise
lib_level = logging.DEBUG if Config.LOG_LEVEL.upper() == "DEBUG" else logging.WARNING
quiet_loggers = [
    "asyncpg",
    "redis", 
    "sentence_transformers",
    "torch",
    "torch._inductor",
    "torch._dynamo", 
    "torch._subclasses",
    "transformers"
]

for logger_name in quiet_loggers:
    lib_logger = logging.getLogger(logger_name)
    lib_logger.setLevel(lib_level)

# Configure our application logger
logger = structlog.get_logger("codebase_knowledge_mcp")

# Log the logging configuration
if Config.LOG_LEVEL.upper() == "DEBUG":
    logger.debug("Logging configuration", 
                app_level=Config.LOG_LEVEL,
                mcp_debug=Config.MCP_DEBUG,
                mcp_level="DEBUG" if Config.MCP_DEBUG else "WARNING",
                lib_level="DEBUG" if Config.LOG_LEVEL.upper() == "DEBUG" else "WARNING")


class ReducedScopeMCPServer:
    """MCP Server with 5 focused tools for codebase knowledge."""
    
    def __init__(self):
        self.server = Server("reduced-scope-codebase-knowledge")
        self.db_pool: Optional[asyncpg.Pool] = None
        self.redis_client: Optional[redis.Redis] = None
        self.knowledge_store: Optional[KnowledgeStore] = None
        self._setup_tools()
        
    def _setup_tools(self):
        """Register all MCP tools."""
        
        # Tool 1: Search project knowledge
        @self.server.list_tools()
        async def handle_list_tools() -> List[Tool]:
            return [
                Tool(
                    name="search_project_knowledge",
                    description="Semantic search across all project knowledge with scope filtering",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query for semantic matching"
                            },
                            "project_id": {
                                "type": "string",
                                "description": "Optional project ID to filter results"
                            },
                            "scope_filter": {
                                "type": "string",
                                "description": "Optional scope prefix to filter (e.g., 'frontend.components')"
                            },
                            "analysis_types": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": ["document", "architecture", "decision", "structure", "semantic", "dependencies", "cross_project_link"]
                                },
                                "description": "Optional filter by analysis types"
                            },
                            "limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 100,
                                "default": 10,
                                "description": "Maximum number of results to return"
                            },
                            "similarity_threshold": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                                "default": 0.5,
                                "description": "Minimum similarity score for results"
                            }
                        },
                        "required": ["query"]
                    }
                ),
                
                Tool(
                    name="get_cached_analysis_with_freshness",
                    description="Retrieve specific analysis with transparent staleness information",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "target_scope": {
                                "type": "string",
                                "description": "Hierarchical scope to retrieve (e.g., 'frontend.components.Button')"
                            },
                            "project_id": {
                                "type": "string",
                                "description": "Optional project ID, defaults to current project"
                            }
                        },
                        "required": ["target_scope"]
                    }
                ),
                
                Tool(
                    name="get_component_architecture", 
                    description="Get deep component architecture with dependencies and relationships",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "component_scope": {
                                "type": "string",
                                "description": "Component scope to analyze (e.g., 'backend.services.UserService')"
                            },
                            "project_id": {
                                "type": "string",
                                "description": "Optional project ID to filter results"
                            },
                            "include_dependencies": {
                                "type": "boolean",
                                "default": True,
                                "description": "Include dependency and dependent analysis"
                            },
                            "include_relationships": {
                                "type": "boolean", 
                                "default": True,
                                "description": "Include similar/related component discovery"
                            }
                        },
                        "required": ["component_scope"]
                    }
                ),
                
                Tool(
                    name="store_analysis_result",
                    description="Store new analysis with hierarchical scope and automatic deduplication",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "analysis_type": {
                                "type": "string",
                                "enum": ["document", "architecture", "decision", "structure", "semantic", "dependencies", "cross_project_link"],
                                "description": "Type of analysis being stored"
                            },
                            "target_scope": {
                                "type": "string",
                                "description": "Hierarchical scope for the analysis (e.g., 'api.endpoints.users')"
                            },
                            "scope_level": {
                                "type": "string",
                                "enum": ["project", "domain", "module", "file"],
                                "description": "Hierarchical level of the scope"
                            },
                            "content": {
                                "type": "string",
                                "description": "Content to analyze and store"
                            },
                            "project_id": {
                                "type": "string",
                                "default": "default",
                                "description": "Project ID for multi-project support"
                            },
                            "source_files": {
                                "type": "array",
                                "items": {"type": "string"},
                                "default": [],
                                "description": "Source files that contributed to this analysis"
                            },
                            "force_refresh": {
                                "type": "boolean",
                                "default": False,
                                "description": "Force analysis even if content hash matches existing"
                            }
                        },
                        "required": ["analysis_type", "target_scope", "scope_level", "content"]
                    }
                ),
                
                Tool(
                    name="manage_knowledge_lifecycle",
                    description="Archive, delete, or cleanup stale knowledge with safety controls",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["archive", "delete", "mark_stale", "refresh", "bulk_cleanup"],
                                "description": "Lifecycle action to perform"
                            },
                            "target_scope": {
                                "type": "string",
                                "description": "Optional scope pattern to target (e.g., 'legacy.*')"
                            },
                            "analysis_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "default": [],
                                "description": "Specific analysis IDs to target"
                            },
                            "older_than_days": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "Target items older than N days"
                            },
                            "analysis_types": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": ["document", "architecture", "decision", "structure", "semantic", "dependencies", "cross_project_link"]
                                },
                                "description": "Target specific analysis types"
                            },
                            "dry_run": {
                                "type": "boolean",
                                "default": True,
                                "description": "Preview operation without executing"
                            },
                            "batch_size": {
                                "type": "integer",
                                "default": 100,
                                "minimum": 1,
                                "maximum": 1000,
                                "description": "Process in batches of N items"
                            }
                        },
                        "required": ["action"]
                    }
                )
            ]
        
        # Tool implementations
        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            if not self.knowledge_store:
                return [TextContent(
                    type="text",
                    text="❌ Knowledge store not initialized. Please check database and Redis connections."
                )]
            
            try:
                if name == "search_project_knowledge":
                    return await self._handle_search_project_knowledge(arguments)
                elif name == "get_cached_analysis_with_freshness":
                    return await self._handle_get_cached_analysis_with_freshness(arguments)
                elif name == "get_component_architecture":
                    return await self._handle_get_component_architecture(arguments)
                elif name == "store_analysis_result":
                    return await self._handle_store_analysis_result(arguments)
                elif name == "manage_knowledge_lifecycle":
                    return await self._handle_manage_knowledge_lifecycle(arguments)
                else:
                    return [TextContent(
                        type="text",
                        text=f"❌ Unknown tool: {name}"
                    )]
            except Exception as e:
                logger.error(f"Tool {name} failed: {e}", exc_info=True)
                return [TextContent(
                    type="text",
                    text=f"❌ Tool execution failed: {str(e)}"
                )]
    
    async def _handle_search_project_knowledge(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle semantic search across project knowledge."""
        
        query = args["query"]
        project_id = args.get("project_id")
        scope_filter = args.get("scope_filter")
        limit = args.get("limit", 10)
        similarity_threshold = args.get("similarity_threshold", 0.5)
        
        # Parse analysis types
        analysis_types = None
        if args.get("analysis_types"):
            analysis_types = [AnalysisType(t) for t in args["analysis_types"]]
        
        # Perform search
        results = await self.knowledge_store.search.search_project_knowledge(
            query=query,
            project_id=project_id,
            scope_filter=scope_filter,
            analysis_types=analysis_types,
            limit=limit,
            similarity_threshold=similarity_threshold
        )
        
        if not results:
            return [TextContent(
                type="text",
                text=f"🔍 No results found for query: '{query}'\n\n" +
                     "Try:\n" +
                     "- Broader search terms\n" + 
                     "- Lower similarity threshold\n" +
                     "- Different scope filters"
            )]
        
        # Format results
        output = [f"🔍 **Search Results for '{query}'** ({len(results)} results)\n"]
        
        for i, result in enumerate(results, 1):
            output.append(f"## {i}. {result.title}")
            output.append(f"**Scope:** `{result.scope}`")
            output.append(f"**Type:** {result.analysis_type.value}")
            output.append(f"**Similarity:** {result.similarity_score:.3f}")
            
            if result.source_file:
                output.append(f"**Source:** {result.source_file}")
            
            output.append(f"**Content Preview:**")
            output.append(f"```")
            output.append(result.content_chunk)
            output.append(f"```")
            output.append("")
        
        return [TextContent(type="text", text="\n".join(output))]
    
    async def _handle_get_cached_analysis_with_freshness(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle retrieval with freshness information."""
        
        target_scope = args["target_scope"]
        project_id = args.get("project_id")
        
        result = await self.knowledge_store.get_cached_analysis_with_freshness(
            target_scope=target_scope,
            project_id=project_id
        )
        
        if not result:
            return [TextContent(
                type="text",
                text=f"❌ No analysis found for scope: `{target_scope}`\n\n" +
                     f"To create analysis for this scope, use `store_analysis_result`."
            )]
        
        # Format response with freshness info
        freshness_emoji = {
            "fresh": "🟢",
            "recent": "🟡", 
            "stale": "🟠",
            "expired": "🔴"
        }
        
        freshness = result.freshness_info
        analysis = result.analysis_result
        
        output = [
            f"## 📊 Analysis: `{target_scope}`",
            "",
            f"### Freshness Status {freshness_emoji.get(freshness.freshness_category.value, '⚪')}",
            f"- **Status:** {freshness.freshness_category.value.title()}",
            f"- **Staleness:** {freshness.staleness_seconds:.0f} seconds",
            f"- **Analysis Time:** {analysis.analysis_timestamp.isoformat()}",
            f"- **Last Scope Change:** {freshness.scope_last_change.isoformat()}",
            f"- **Freshness Score:** {freshness.freshness_score:.3f}",
            "",
            f"### Analysis Details",
            f"- **Type:** {analysis.analysis_type.value}",
            f"- **Project:** {analysis.project_id}",
            f"- **Scope Level:** {analysis.scope_level.value}",
            f"- **Source Files:** {len(analysis.source_files)} files",
            "",
            f"### Content",
            "```json",
            json.dumps(analysis.result_data, indent=2),
            "```",
            "",
            f"### Recommendations",
        ]
        
        for rec in freshness.recommendations:
            output.append(f"- {rec}")
        
        output.extend([
            "",
            f"### Performance",
            f"- **Query Duration:** {result.query_duration_ms:.1f}ms",
            f"- **Cache Hit:** {'Yes' if result.cache_hit else 'No'}",
        ])
        
        return [TextContent(type="text", text="\n".join(output))]
    
    async def _handle_get_component_architecture(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle component architecture retrieval."""
        
        component_scope = args["component_scope"]
        project_id = args.get("project_id")
        include_dependencies = args.get("include_dependencies", True)
        include_relationships = args.get("include_relationships", True)
        
        architecture = await self.knowledge_store.get_component_architecture(
            component_scope=component_scope,
            project_id=project_id,
            include_dependencies=include_dependencies,
            include_relationships=include_relationships
        )
        
        if not architecture:
            return [TextContent(
                type="text",
                text=f"❌ No architecture found for component: `{component_scope}`\n\n" +
                     "Make sure the component has been analyzed and stored."
            )]
        
        # Format architecture response
        output = [
            f"## 🏗️ Component Architecture: `{component_scope}`",
            "",
            f"### Component Details",
            f"- **Type:** {architecture['component']['analysis_type']}",
            f"- **Project:** {architecture['component']['project_id']}",
            f"- **Scope Level:** {architecture['component']['scope_level']}",
            "",
            f"### Freshness",
            f"- **Status:** {architecture['freshness']['freshness_category']}",
            f"- **Score:** {architecture['freshness']['freshness_score']:.3f}",
            ""
        ]
        
        if include_dependencies and architecture.get("dependencies"):
            output.extend([
                f"### 🔗 Dependencies ({len(architecture['dependencies'])})",
                ""
            ])
            for dep in architecture["dependencies"]:
                output.append(f"- **{dep['target_scope']}** ({dep['analysis_type']})")
            output.append("")
        
        if include_dependencies and architecture.get("dependents"):
            output.extend([
                f"### ⬅️ Dependents ({len(architecture['dependents'])})",
                ""
            ])
            for dep in architecture["dependents"]:
                output.append(f"- **{dep['target_scope']}** ({dep['analysis_type']})")
            output.append("")
        
        if include_relationships and architecture.get("related_components"):
            output.extend([
                f"### 🔍 Related Components ({len(architecture['related_components'])})",
                ""
            ])
            for rel in architecture["related_components"]:
                output.append(f"- **{rel['scope']}** (similarity: {rel['similarity_score']:.3f})")
            output.append("")
        
        # Add main component data
        output.extend([
            f"### 📋 Component Data",
            "```json",
            json.dumps(architecture['component']['result_data'], indent=2),
            "```"
        ])
        
        return [TextContent(type="text", text="\n".join(output))]
    
    async def _handle_store_analysis_result(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle storing new analysis."""
        
        request = StorageRequest(
            analysis_type=AnalysisType(args["analysis_type"]),
            target_scope=args["target_scope"],
            scope_level=ScopeLevel(args["scope_level"]),
            content=args["content"],
            source_files=args.get("source_files", []),
            force_refresh=args.get("force_refresh", False)
        )
        
        project_id = args.get("project_id", "default")
        
        result = await self.knowledge_store.store_analysis_result(
            request=request,
            project_id=project_id
        )
        
        # Format storage response
        if result.was_deduplicated:
            output = [
                f"♻️ **Analysis Deduplicated**",
                "",
                f"Existing analysis found with matching content hash.",
                f"- **Analysis ID:** `{result.existing_analysis_id}`",
                f"- **Scope:** `{request.target_scope}`",
                f"- **Project:** `{project_id}`",
                f"- **Storage Duration:** {result.storage_duration_ms:.1f}ms",
                "",
                f"💡 Use `force_refresh=true` to override deduplication."
            ]
        else:
            output = [
                f"✅ **Analysis Stored Successfully**",
                "",
                f"- **Analysis ID:** `{result.analysis_id}`",
                f"- **Scope:** `{request.target_scope}`",
                f"- **Type:** {request.analysis_type.value}",
                f"- **Level:** {request.scope_level.value}",
                f"- **Project:** `{project_id}`",
                f"- **Source Files:** {len(request.source_files)} files",
                "",
                f"### Performance",
                f"- **Storage Duration:** {result.storage_duration_ms:.1f}ms",
                f"- **Analysis Duration:** {result.analysis_duration_ms:.1f}ms" if result.analysis_duration_ms else "",
                "",
                f"✨ Analysis is now searchable and cached for fast retrieval."
            ]
        
        return [TextContent(type="text", text="\n".join(output))]
    
    async def _handle_manage_knowledge_lifecycle(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle knowledge lifecycle management."""
        
        request = LifecycleRequest(
            action=LifecycleAction(args["action"]),
            target_scope=args.get("target_scope"),
            analysis_ids=[args["analysis_ids"]] if "analysis_ids" in args else [],
            older_than_days=args.get("older_than_days"),
            analysis_types=[AnalysisType(t) for t in args.get("analysis_types", [])],
            dry_run=args.get("dry_run", True),
            batch_size=args.get("batch_size", 100)
        )
        
        result = await self.knowledge_store.manage_knowledge_lifecycle(request)
        
        # Format lifecycle response
        action_emoji = {
            "archive": "📦",
            "delete": "🗑️",
            "mark_stale": "⚠️",
            "refresh": "🔄",
            "bulk_cleanup": "🧹"
        }
        
        emoji = action_emoji.get(request.action.value, "⚙️")
        action_name = request.action.value.replace("_", " ").title()
        
        output = [
            f"{emoji} **{action_name} {'(Dry Run)' if result.was_dry_run else '(Executed)'}**",
            "",
            f"### Results",
            f"- **Items Affected:** {result.items_affected}",
            f"- **Items Archived:** {result.items_archived}",
            f"- **Items Deleted:** {result.items_deleted}",
            f"- **Items Marked Stale:** {result.items_marked_stale}",
            f"- **Items Queued for Refresh:** {result.items_queued_refresh}",
            "",
            f"### Operation Details",
            f"- **Target Scope:** `{result.target_scope or 'All'}`",
            f"- **Duration:** {result.operation_duration_ms:.1f}ms",
            f"- **Timestamp:** {result.execution_timestamp.isoformat()}",
        ]
        
        if result.errors:
            output.extend([
                "",
                f"### ⚠️ Errors ({len(result.errors)})",
                ""
            ])
            for error in result.errors:
                output.append(f"- {error}")
        
        if result.warnings:
            output.extend([
                "",
                f"### ⚠️ Warnings ({len(result.warnings)})",
                ""
            ])
            for warning in result.warnings:
                output.append(f"- {warning}")
        
        if result.was_dry_run:
            output.extend([
                "",
                f"💡 This was a dry run. Use `dry_run=false` to execute the operation."
            ])
        
        return [TextContent(type="text", text="\n".join(output))]
    
    async def initialize(self):
        """Initialize database connections and knowledge store."""
        try:
            # Initialize database pool
            logger.info("Connecting to PostgreSQL", 
                       database_url=Config.DATABASE_URL[:50] + "..." if len(Config.DATABASE_URL) > 50 else Config.DATABASE_URL)
            self.db_pool = await asyncpg.create_pool(**Config.get_database_config())
            logger.info("PostgreSQL connection established", pool_size=self.db_pool._minsize)
            
            # Initialize Redis
            logger.info("Connecting to Redis", redis_url=Config.REDIS_URL)
            self.redis_client = redis.from_url(**Config.get_redis_config())
            await self.redis_client.ping()
            logger.info("Redis connection established")
            
            # Initialize knowledge store
            logger.info("Initializing knowledge store")
            self.knowledge_store = KnowledgeStore(self.db_pool, self.redis_client)
            await self.knowledge_store.initialize()
            logger.info("Knowledge store initialized")
            
            logger.info("MCP Server initialized successfully", 
                       server_name="codebase-knowledge-mcp",
                       tools_count=5)
            
        except asyncpg.exceptions.ConnectionDoesNotExistError as e:
            logger.error("PostgreSQL connection failed - database may not exist", 
                        error=str(e), 
                        database_url=Config.DATABASE_URL[:50] + "...")
            raise
        except redis.exceptions.ConnectionError as e:
            logger.error("Redis connection failed - Redis server may not be running", 
                        error=str(e),
                        redis_url=Config.REDIS_URL)
            raise
        except Exception as e:
            logger.error("Server initialization failed", 
                        error=str(e), 
                        error_type=type(e).__name__,
                        exc_info=True)
            raise
    
    async def cleanup(self):
        """Clean up resources."""
        try:
            if self.redis_client:
                logger.info("Closing Redis connection")
                await self.redis_client.close()
                
            if self.db_pool:
                logger.info("Closing database pool")
                await self.db_pool.close()
                
            logger.info("Server cleanup completed successfully")
        except Exception as e:
            logger.error("Error during cleanup", 
                        error=str(e), 
                        error_type=type(e).__name__)
    
    async def run(self):
        """Run the MCP server."""
        try:
            await self.initialize()
            
            # Check health before starting
            health = await self.knowledge_store.get_health_status()
            if health.status != "healthy":
                logger.warning("Server starting with degraded health", 
                              health_status=health.status,
                              database_connected=health.database_connected,
                              redis_connected=health.redis_connected)
            else:
                logger.info("Health check passed", 
                           total_analyses=health.total_analyses,
                           cache_hit_rate=health.cache_hit_rate)
            
            logger.info("Starting MCP stdio server", 
                       protocol="stdio",
                       tools_available=5)
            
            # Run the stdio server
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    self.server.create_initialization_options()
                )
                
        except KeyboardInterrupt:
            logger.info("Server shutdown requested by user")
        except Exception as e:
            logger.error("Server runtime error", 
                        error=str(e), 
                        error_type=type(e).__name__,
                        exc_info=True)
            raise
        finally:
            logger.info("Shutting down server")
            await self.cleanup()


async def main():
    """Main entry point."""
    try:
        logger.info("Starting Codebase Knowledge MCP Server", 
                   version="0.1.6",
                   python_version=sys.version.split()[0])
        server = ReducedScopeMCPServer()
        await server.run()
    except Exception as e:
        logger.error("Failed to start server", 
                    error=str(e), 
                    error_type=type(e).__name__,
                    exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
