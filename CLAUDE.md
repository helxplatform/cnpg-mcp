# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Model Context Protocol (MCP) server** for managing PostgreSQL clusters using the CloudNativePG operator in Kubernetes. It provides a bridge between LLMs and CloudNativePG resources, enabling natural language interaction with PostgreSQL cluster lifecycle management.

**Key characteristics:**
- Python-based MCP server using the official `mcp` SDK
- Kubernetes client interacting with CloudNativePG Custom Resources (CRDs)
- Designed for transport-agnostic architecture (currently stdio, future HTTP/SSE support)
- All operations are async using Python asyncio

## Development Commands

### Running the Server

```bash
# Default stdio transport (for Claude Desktop integration)
python cnpg_mcp_server.py

# With specific transport mode
python cnpg_mcp_server.py --transport stdio

# HTTP transport (requires additional dependencies - not yet implemented)
python cnpg_mcp_server.py --transport http --port 3000
```

### Testing

```bash
# Syntax check
python -m py_compile cnpg_mcp_server.py

# Test Kubernetes connectivity
kubectl get nodes
kubectl get clusters -A  # List CloudNativePG clusters

# Deploy test cluster
kubectl apply -f example-cluster.yaml

# Check cluster status
kubectl get cluster example-cluster -w
```

### Dependencies

```bash
# Install core dependencies
pip install -r requirements.txt

# For HTTP transport (when implementing)
pip install 'mcp[sse]' starlette uvicorn python-multipart
```

### RBAC Setup

**Important:** CloudNativePG helm chart automatically creates ClusterRoles. You only need to create ServiceAccount + RoleBindings.

**Option 1: Using Python script (recommended):**
```bash
# Install dependencies (if not already installed)
pip install -r requirements.txt

# Create ServiceAccount and bind to edit role
python rbac/bind_cnpg_role.py --namespace default --service-account cnpg-mcp-server

# For read-only access
python rbac/bind_cnpg_role.py --namespace default --service-account cnpg-mcp-server --role view

# Dry run to see what would be created
python rbac/bind_cnpg_role.py --dry-run
```

**Option 2: Using kubectl:**
```bash
# Apply RBAC configuration (creates ServiceAccount and binds to existing cnpg roles)
kubectl apply -f rbac.yaml
```

**Verify setup:**
```bash
# Verify the helm-created roles exist
kubectl get clusterroles | grep cnpg
# Should show: cnpg-cloudnative-pg, cnpg-cloudnative-pg-edit, cnpg-cloudnative-pg-view

# Verify permissions for the service account
kubectl auth can-i get clusters.postgresql.cnpg.io --as=system:serviceaccount:default:cnpg-mcp-server
kubectl auth can-i create clusters.postgresql.cnpg.io --as=system:serviceaccount:default:cnpg-mcp-server
```

**Available CloudNativePG roles:**
- `cnpg-cloudnative-pg-edit`: Full edit access (recommended, used by default)
- `cnpg-cloudnative-pg-view`: Read-only access
- `cnpg-cloudnative-pg`: Full admin access

## Architecture

### Transport-Agnostic Design

The server architecture separates transport concerns from business logic:

```
MCP Tools (@mcp.tool() decorated functions)
    ↓ (transport-agnostic)
Transport Layer (stdio or HTTP/SSE)
    ↓
Kubernetes API (CustomObjectsApi + CoreV1Api)
    ↓
CloudNativePG Operator
```

**Key architectural points:**
- All tool functions work with any transport mode
- Transport selection happens at startup via `main()` → `run_stdio_transport()` or `run_http_transport()`
- Kubernetes clients initialized once globally: `custom_api` (CustomObjectsApi) and `core_api` (CoreV1Api)
- All I/O operations use `asyncio.to_thread()` to prevent blocking the event loop

### Core Components

**cnpg_mcp_server.py** (single-file architecture, ~712 lines):
- Lines 1-60: Imports, configuration, Kubernetes client initialization
- Lines 61-120: Utility functions (`truncate_response`, `format_error_message`)
- Lines 121-189: Kubernetes API helpers (`get_cnpg_cluster`, `list_cnpg_clusters`, `format_cluster_status`)
- Lines 190-268: Pydantic models for input validation
- Lines 269-590: MCP tool implementations (4 tools: list, get, create, scale)
- Lines 591-640: Transport implementations (`run_stdio_transport`, `run_http_transport`)
- Lines 641-712: CLI argument parsing and main entry point

### MCP Tools

The server exposes 4 tools to LLMs:

1. **list_postgres_clusters** (line 276): List all clusters with optional namespace filtering
2. **get_cluster_status** (line 328): Get detailed status for a specific cluster
3. **create_postgres_cluster** (line 373): Create new PostgreSQL cluster with HA configuration
4. **scale_postgres_cluster** (line 499): Scale cluster by adjusting instance count

**Tool implementation pattern:**
- Decorated with `@mcp.tool()`
- Comprehensive docstrings with Args, Returns, Examples, Error Handling sections
- Use Pydantic models for input validation (though not explicitly enforced in decorator)
- Return formatted strings optimized for LLM consumption
- Error handling via `format_error_message()` with actionable suggestions

### CloudNativePG Integration

**Resource structure:**
- Group: `postgresql.cnpg.io`
- Version: `v1`
- Kind: `Cluster`
- Plural: `clusters`

**Key fields in Cluster spec:**
- `spec.instances`: Number of PostgreSQL instances (for HA)
- `spec.imageName`: PostgreSQL version (e.g., `ghcr.io/cloudnative-pg/postgresql:16`)
- `spec.storage.size`: Storage per instance
- `spec.postgresql.parameters`: PostgreSQL configuration parameters

**Key fields in Cluster status:**
- `status.phase`: Overall cluster phase (e.g., "Cluster in healthy state")
- `status.readyInstances`: Count of ready instances
- `status.currentPrimary`: Name of current primary pod
- `status.conditions`: Array of condition objects

### Response Formatting

- **Character limit**: 25,000 characters (CHARACTER_LIMIT constant)
- **Truncation**: Applied via `truncate_response()` to prevent context overflow
- **Detail levels**: "concise" (default) vs "detailed" for progressive disclosure
- **Error messages**: Structured with status code, message, and actionable suggestions

## Code Conventions

### Adding New MCP Tools

Follow this pattern when adding tools:

1. **Create Pydantic model** for input validation (lines 190-268 area)
```python
class MyToolInput(BaseModel):
    """Input for my_tool."""
    param1: str = Field(..., description="Clear description with examples")
```

2. **Implement tool function** (after existing tools, around line 590)
```python
@mcp.tool()
async def my_tool(param1: str, param2: Optional[str] = None) -> str:
    """
    Brief description.

    Detailed explanation of what this tool does and when to use it.

    Args:
        param1: Parameter description with usage guidance
        param2: Optional parameter description

    Returns:
        Description of return value format

    Examples:
        - Example usage 1
        - Example usage 2

    Error Handling:
        - Common error scenarios and resolution steps
    """
    try:
        # Implementation
        result = await some_async_operation(param1, param2)
        return truncate_response(format_result(result))
    except Exception as e:
        return format_error_message(e, "context description")
```

3. **Use async/await for Kubernetes calls**
```python
cluster = await asyncio.to_thread(
    custom_api.get_namespaced_custom_object,
    group=CNPG_GROUP,
    version=CNPG_VERSION,
    namespace=namespace,
    plural=CNPG_PLURAL,
    name=name
)
```

### Error Handling Strategy

- Always use try/except blocks in tool functions
- Format errors via `format_error_message(error, context)`
- Provide actionable suggestions based on HTTP status codes:
  - 404: Resource not found → suggest listing or checking namespace
  - 403: Permission denied → suggest RBAC verification
  - 409: Conflict → suggest resource may already exist
  - 422: Invalid spec → suggest checking API documentation

### Testing Kubernetes Operations

When testing or debugging Kubernetes operations:

```bash
# Directly inspect resources
kubectl get clusters -A -o yaml
kubectl describe cluster <name> -n <namespace>

# Check operator logs
kubectl logs -n cnpg-system deployment/cnpg-controller-manager

# Test API access
kubectl auth can-i get clusters.postgresql.cnpg.io --as=system:serviceaccount:default:cnpg-mcp-server

# Get connection credentials
kubectl get secret <cluster-name>-app -o jsonpath='{.data.password}' | base64 -d
```

## Important Notes

### Transport Modes

- **stdio (default)**: Uses stdin/stdout, perfect for Claude Desktop, single client only
- **HTTP (future)**: Requires implementing `run_http_transport()` skeleton at line 604-640
  - Uncomment dependencies in requirements.txt
  - Implement SSE transport using `mcp.server.sse.SseServerTransport`
  - Add authentication middleware (required for production)
  - See HTTP_TRANSPORT_GUIDE.md for full implementation guide

### Kubernetes Configuration

- **In-cluster**: Uses service account tokens automatically
- **Local**: Uses `~/.kube/config` or `KUBECONFIG` environment variable
- Initialization at line 45-60 attempts in-cluster first, falls back to kubeconfig

### Response Optimization

- Responses are optimized for LLM consumption (markdown formatting, concise by default)
- Use `detail_level="detailed"` parameter for comprehensive information
- Always truncate responses to stay within CHARACTER_LIMIT (25,000 chars)

### Security Considerations

- **RBAC**: Uses CloudNativePG's built-in roles (no custom ClusterRoles needed)
  - rbac.yaml binds to `cnpg-cloudnative-pg-edit` by default
  - For read-only, change to `cnpg-cloudnative-pg-view`
  - Follow principle of least privilege
- Never log or expose database credentials
- All inputs validated via Pydantic models
- Consider namespace isolation for multi-tenant scenarios

## Common Tasks

### Debugging Connection Issues

```bash
# Check Kubernetes connectivity
kubectl cluster-info
kubectl get nodes

# Verify CloudNativePG operator is running
kubectl get deployment -n cnpg-system cnpg-controller-manager

# Check server can load config
python -c "from kubernetes import config; config.load_kube_config(); print('OK')"
```

### Extending Tool Capabilities

Current tools are focused on cluster lifecycle (list, get, create, scale). Natural extensions:

- Backup management (list_backups, create_backup, restore_backup)
- Pod logs retrieval (get_cluster_logs)
- Connection information (get_connection_info)
- Database operations (create_database, create_user) - with safety guardrails
- Monitoring metrics integration

When adding these, follow the existing patterns for async operations, error handling, and response formatting.

### Deployment Considerations

- **Development**: Run locally with `python cnpg_mcp_server.py`
- **Production**: Use kubernetes-deployment.yaml with proper RBAC
- **Claude Desktop**: Configure in `claude_desktop_config.json` with absolute path
- **Container**: Use provided Dockerfile (Python 3.11-slim base)

## File Organization

- **cnpg_mcp_server.py**: Main server implementation (single file)
- **requirements.txt**: Python dependencies (core only, HTTP commented out)
- **rbac.yaml**: Kubernetes RBAC configuration
- **example-cluster.yaml**: Sample PostgreSQL cluster manifest
- **kubernetes-deployment.yaml**: K8s Deployment and Service for the MCP server
- **Dockerfile**: Container image definition
- **QUICKSTART.md**: Quick start guide for new users
- **HTTP_TRANSPORT_GUIDE.md**: Guide for implementing HTTP transport
- **REFACTORING_SUMMARY.md**: Explains transport-agnostic refactoring

## Related Resources

- CloudNativePG API: https://cloudnative-pg.io/documentation/current/
- MCP Protocol: https://modelcontextprotocol.io/
- Kubernetes Python Client: https://github.com/kubernetes-client/python
