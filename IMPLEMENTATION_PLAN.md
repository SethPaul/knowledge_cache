# Reduced Scope MCP Server - Implementation Plan

## 🎯 Project Vision

Build a **highly polished, production-ready MCP server** focused exclusively on the **4 core tools** that provide maximum value to AI agents working with codebase knowledge.

Based on analysis of the existing codebase and the [AWS MCP blog insights](https://aws.amazon.com/blogs/machine-learning/unlocking-the-power-of-model-context-protocol-mcp-on-aws/), this reduced scope will solve the "M×N integration problem" for codebase intelligence with enterprise-grade reliability.

---

## 🔧 Core 5 Tools (Only These)

### 1. `search_project_knowledge`
**Purpose**: Semantic search across all project knowledge
**Priority**: **P0** - Foundation for all agent discovery patterns

### 2. `get_cached_analysis_with_freshness`  
**Purpose**: Retrieve analysis with transparent staleness information
**Priority**: **P0** - Enables reliable agent decision-making

### 3. `get_component_architecture`
**Purpose**: Deep component understanding and relationships
**Priority**: **P0** - Powers impact analysis and cross-component discovery

### 4. `store_analysis_result`
**Purpose**: Store knowledge with hierarchical distribution  
**Priority**: **P0** - Enables knowledge growth and agent learning

### 5. `manage_knowledge_lifecycle`
**Purpose**: Archive, remove, and cleanup stale or inaccurate knowledge
**Priority**: **P0** - Maintains data quality and prevents knowledge pollution

---

## 📋 What to Keep from Existing Work

### ✅ **Excellent Patterns to Preserve**

#### **1. Hierarchical Scope Architecture**
```python
# From: components/knowledge_store/src/knowledge_store/models.py
class ScopeLevel(str, Enum):
    PROJECT = "project"
    DOMAIN = "domain"  
    MODULE = "module"
    FILE = "file"

# Usage: "project.components.knowledge_store.api"
```
**Why Keep**: Perfect for efficient querying and knowledge organization

#### **2. Freshness Management with Timestamps**
```python
# From: components/knowledge_store/src/knowledge_store/models.py  
class FreshnessInfo(BaseModel):
    staleness_seconds: float
    freshness_category: FreshnessCategory
    scope_last_change: datetime
    analysis_timestamp: datetime
    scope_path: str
    scope_level: ScopeLevel
    freshness_score: float = Field(..., ge=0.0, le=1.0)
    recommendations: List[str]
```
**Why Keep**: Transparent, actionable freshness information for agents

#### **3. Content Addressing for Change Detection**
```python
# From: components/knowledge_store/src/knowledge_store/models.py
class AnalysisResult(BaseModel):
    content_hash: str = Field(..., description="Hash of source content")
    dependencies_hash: Optional[str] = Field(None, description="Hash of dependency inputs")
```
**Why Keep**: Efficient change detection without expensive re-analysis

#### **4. Structured Logging Pattern**
```python
# From: mvp/mvp/server.py
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)
```
**Why Keep**: Production-ready observability

#### **5. MCP Tool Schema Structure**
```python
# From: mvp/mcp_stdio_server.py
{
    "name": "search_project_knowledge",
    "description": "Search across project documentation and design decisions",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "scope_filter": {"type": "string", "description": "Optional scope filter"},
            "limit": {"type": "integer", "description": "Max results", "default": 10}
        },
        "required": ["query"]
    }
}
```
**Why Keep**: Clear, standardized interface for agent integration

### ✅ **Core Infrastructure to Preserve**

#### **PostgreSQL + pgvector Foundation**
- **Database Schema**: Hierarchical storage with vector search
- **Connection Pooling**: asyncpg for performance
- **Vector Operations**: pgvector for semantic search

#### **FastAPI + Pydantic Stack**
- **Type Safety**: Pydantic models for validation
- **Async Operations**: FastAPI for concurrent handling
- **Auto Documentation**: Built-in schema generation

#### **Redis Caching Strategy**
- **Multi-Level Cache**: L1 (memory) → L2 (Redis) → L3 (PostgreSQL)
- **Cache Invalidation**: Scope-based invalidation patterns

---

## ❌ **What to Remove/Simplify**

### **1. Complex Bootstrap System**
**Current**: 4 bootstrap tools with complex progress tracking
**New**: Simple, synchronous analysis on-demand
**Reason**: Adds complexity without core value for 4-tool focus

### **2. Multiple Server Implementations**
**Current**: FastAPI HTTP + stdio + potential SSE
**New**: Focus on **stdio only** for MCP compliance
**Reason**: stdio is the standard, others add maintenance overhead

### **3. Document-Specific Models**
**Current**: Separate DocumentAnalysis, DesignDecision models
**New**: Unified AnalysisResult for all content types
**Reason**: Simpler data model for broader content support

### **4. Complex Component System**
**Current**: 5 separate components (bootstrap_analyzer, change_detector, etc.)
**New**: Single, focused knowledge store
**Reason**: Over-engineered for 4-tool scope

### **5. Multiple Configuration Systems**
**Current**: Environment files, YAML configs, multiple initialization paths
**New**: Simple environment-based configuration
**Reason**: Reduces complexity and failure points

---

## 🏗️ **New Architecture Design**

### **Simplified Component Structure**
```
reduced_scope/
├── server.py              # MCP stdio server (single entry point)
├── knowledge_store.py     # Core storage operations
├── models.py              # Focused data models
├── freshness.py           # Timestamp-based freshness management
├── search.py              # Semantic search operations
├── config.py              # Simple environment configuration
├── schema.sql             # Database schema (PostgreSQL + pgvector)
├── requirements.txt       # Dependencies
└── tests/                 # Focused test suite
```

### **Single Responsibility Principle**
- **server.py**: MCP protocol handling only
- **knowledge_store.py**: CRUD operations only
- **search.py**: Search algorithm only
- **freshness.py**: Timestamp management only

### **Performance-First Design**
- **Connection Pooling**: Single asyncpg pool, shared across operations
- **Query Optimization**: Prepared statements for core queries
- **Cache Strategy**: Redis for hot data, PostgreSQL for cold storage
- **Batch Operations**: Bulk inserts and updates where possible

---

## 🎯 **Key Learnings to Apply**

### **1. Agent-Centric Design**
**Learning**: Agents need clear confidence scores and actionable recommendations
**Application**: Every response includes freshness info and next-step guidance

### **2. Failure Isolation**
**Learning**: Individual tool failures shouldn't cascade
**Application**: Each tool has independent error handling and graceful degradation

### **3. Transparent Performance**
**Learning**: Agents make better decisions with timing information
**Application**: Include query_duration_ms in all responses

### **4. Hierarchical Efficiency**
**Learning**: Scope-based operations are much more efficient than file-based
**Application**: All operations organized around hierarchical scopes

### **5. Content Addressing Benefits**
**Learning**: Hash-based change detection eliminates expensive re-analysis
**Application**: Content hashing built into all storage operations

---

## 📊 **Success Metrics**

### **Performance Targets**
- **Tool Response Time**: P95 < 100ms for cached operations
- **Search Quality**: Average relevance score > 0.8
- **Cache Hit Rate**: > 85% for repeated queries
- **Concurrent Agents**: Support 20+ simultaneous agent sessions

### **Reliability Targets**  
- **Uptime**: 99.9% availability
- **Error Rate**: < 0.1% tool call failures
- **Data Integrity**: 100% consistency between cache and source
- **Recovery Time**: < 30 seconds from failures

### **Agent Experience Targets**
- **Tool Composition**: Agents successfully combine tools in 90%+ workflows
- **Confidence Usage**: Agents use freshness scores for decision-making
- **Knowledge Growth**: Agents contribute back knowledge via store_analysis_result

---

## 🚀 **Implementation Phases**

### **Phase 1: Foundation (Week 1)**
- [ ] Set up PostgreSQL schema with pgvector
- [ ] Implement core data models (AnalysisResult, FreshnessInfo)
- [ ] Build basic knowledge_store.py with CRUD operations
- [ ] Create simple stdio MCP server

### **Phase 2: Core Tools (Week 2)**
- [ ] Implement `search_project_knowledge` with semantic search
- [ ] Implement `get_cached_analysis_with_freshness`  
- [ ] Add Redis caching layer
- [ ] Build comprehensive test suite

### **Phase 3: Advanced Tools (Week 3)**
- [ ] Implement `get_component_architecture` with relationship mapping
- [ ] Implement `store_analysis_result` with hierarchical distribution
- [ ] Add freshness management and timestamp tracking
- [ ] Performance optimization and query tuning

### **Phase 4: Production Polish (Week 4)**
- [ ] Error handling and graceful degradation
- [ ] Monitoring and observability
- [ ] Load testing and performance validation
- [ ] Documentation and deployment guides

---

## 🔗 **Integration Points**

### **MCP Ecosystem Compatibility**
- **Standards Compliance**: Full MCP protocol support for tools/list and tools/call
- **Transport Layer**: stdio for universal IDE compatibility (Cursor, Claude Desktop, Windsurf)
- **Schema Validation**: JSON Schema for all tool inputs/outputs

### **AWS Cloud Readiness**
Based on [AWS MCP implementation patterns](https://aws.amazon.com/blogs/machine-learning/unlocking-the-power-of-model-context-protocol-mcp-on-aws/):
- **IAM Integration**: Ready for AWS security models
- **Bedrock Compatibility**: Compatible with Amazon Bedrock agents
- **Scalability**: Architecture supports horizontal scaling

### **Enterprise Features**
- **Security**: Built-in authentication and authorization hooks
- **Monitoring**: Prometheus metrics and structured logging
- **Deployment**: Docker containerization and Kubernetes manifests

---

## 📖 **Documentation Strategy**

### **Agent Developer Focus**
- **Quick Start**: 5-minute setup guide for common workflows
- **Tool Reference**: Complete schema and examples for each tool
- **Composition Patterns**: Common multi-tool workflows
- **Performance Guide**: Optimization tips for agent developers

### **Operations Focus**
- **Deployment Guide**: Production setup and configuration
- **Monitoring Playbook**: Key metrics and alerting
- **Troubleshooting**: Common issues and solutions
- **Scaling Guide**: Performance tuning and capacity planning

---

## 📊 **Ecosystem Learnings Integration**

Based on our [comprehensive analysis of existing MCP servers](./MCP_ECOSYSTEM_ANALYSIS.md), we've identified key patterns to adopt and extend:

### **✅ Proven Patterns We're Adopting:**

#### **From Vectorize** (Advanced Retrieval)
```python
# Apply their text chunking and vector search optimizations
class OptimizedVectorSearch:
    async def chunk_content_optimally(self, content: str) -> List[str]:
        """Adopt Vectorize's chunking strategies for better embeddings"""
        
    async def advanced_vector_retrieval(self, query_embedding: List[float]) -> List[SearchResult]:
        """Apply their advanced retrieval algorithms"""
```

#### **From Memory** (Knowledge Relationships)
```python
# Apply their relationship tracking for cross-project references
class KnowledgeRelationships:
    async def track_entity_relationships(self, source: str, target: str, relationship_type: str):
        """Adopt Memory's relationship patterns for cross-project links"""
        
    async def traverse_knowledge_graph(self, start_entity: str, depth: int = 3):
        """Apply their graph traversal for impact analysis"""
```

#### **From MCP Plexus** (Multi-Tenant Architecture) 
```python
# Apply their multi-tenant patterns for multi-project support
class MultiProjectArchitecture:
    async def get_project_scoped_context(self, project_id: str) -> ProjectContext:
        """Project-scoped operations like tenant-scoped operations"""
        
    async def secure_cross_project_operation(self, source_project: str, target_project: str):
        """Secure cross-project operations with proper access controls"""
```

#### **From Enterprise Servers** (Security & Audit)
```python
# Apply AWS/Atlan security patterns for enterprise readiness
class EnterpriseFeatures:
    async def audit_knowledge_operation(self, operation: str, user: str, scope: str):
        """Comprehensive audit logging for compliance"""
        
    async def role_based_access_control(self, user: str, project_id: str, operation: str):
        """Role-based access control for project knowledge"""
```

### **🔄 Our Unique Extensions:**

#### **Multi-Project First-Class Support**
```python
# No existing server has this - our unique innovation
class MultiProjectIntelligence:
    async def cross_project_impact_analysis(self, change_scope: str) -> CrossProjectImpact:
        """Analyze impact across multiple connected projects"""
        
    async def unified_multi_project_search(self, query: str) -> UnifiedSearchResults:
        """Search across all projects with project-aware ranking"""
```

#### **Hierarchical Knowledge Organization**
```python
# No existing server has scope-based hierarchical organization
class HierarchicalKnowledge:
    async def scope_based_query_optimization(self, scope: str, query: str) -> OptimizedResults:
        """Leverage hierarchical structure for efficient querying"""
        
    async def hierarchical_freshness_management(self, scope: str) -> FreshnessInfo:
        """Transparent staleness tracking using scope hierarchy"""
```

### **📈 Competitive Advantages from Ecosystem Analysis:**

| **Our Innovation** | **Market Gap** | **Value Proposition** |
|-------------------|----------------|----------------------|
| **Multi-Project Intelligence** | No MCP server handles multiple projects | "First MCP server for enterprise multi-project setups" |
| **Cross-Project References** | Basic relationships in Memory only | "LinkedIn for your codebase - see how projects connect" |
| **Knowledge Lifecycle** | No server manages knowledge aging | "Self-cleaning knowledge that stays accurate" |
| **Hierarchical Freshness** | No transparent staleness information | "Always know how fresh your knowledge is" |

---

This reduced scope approach takes the **best learnings** from your existing work while **eliminating complexity** that doesn't directly serve the 4 core tools. The result will be a **production-ready, enterprise-grade MCP server** that agents can rely on for codebase intelligence. 