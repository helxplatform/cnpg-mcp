# CloudNativePG MCP Server

An MCP (Model Context Protocol) server for managing PostgreSQL clusters using the [CloudNativePG](https://cloudnative-pg.io/) operator in Kubernetes.

## Overview

This MCP server enables LLMs to interact with PostgreSQL clusters managed by the CloudNativePG operator. It provides high-level workflow tools for:

- 📋 Listing and discovering PostgreSQL clusters
- 🔍 Getting detailed cluster status and health information
- 🚀 Creating new PostgreSQL clusters with best practices
- 📈 Scaling clusters up or down
- 🔄 Managing backups and restores (TODO)
- 📊 Monitoring cluster health and logs (TODO)

## Prerequisites

1. **Kubernetes Cluster** with CloudNativePG operator installed:
   ```bash
   kubectl apply -f https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.22/releases/cnpg-1.22.0.yaml
   ```

2. **Python 3.9+** installed

3. **kubectl** configured to access your cluster

4. **Appropriate RBAC permissions** for the service account (see RBAC Setup below)

## Installation

1. Clone or download this repository

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Verify Kubernetes connectivity:
   ```bash
   kubectl get nodes
   ```

## RBAC Setup

The MCP server needs permissions to interact with CloudNativePG resources. Create a service account with appropriate permissions:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: cnpg-mcp-server
  namespace: default
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cnpg-mcp-role
rules:
  # CloudNativePG cluster resources
  - apiGroups: ["postgresql.cnpg.io"]
    resources: ["clusters", "backups", "scheduledbackups"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  # For reading logs and events
  - apiGroups: [""]
    resources: ["pods", "pods/log", "events"]
    verbs: ["get", "list", "watch"]
  # For managing secrets (connection credentials)
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "list", "create", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: cnpg-mcp-binding
subjects:
  - kind: ServiceAccount
    name: cnpg-mcp-server
    namespace: default
roleRef:
  kind: ClusterRole
  name: cnpg-mcp-role
  apiGroup: rbac.authorization.k8s.io
```

Apply the RBAC configuration:
```bash
kubectl apply -f rbac.yaml
```

## Configuration

### Transport Modes

The server supports two transport modes (currently only stdio is implemented):

#### 1. **stdio Transport (Default)**

Communication over stdin/stdout. Best for local development and Claude Desktop integration.

```bash
# Run with default stdio transport
python cnpg_mcp_server.py

# Or explicitly specify stdio
python cnpg_mcp_server.py --transport stdio
```

**Characteristics:**
- ✅ Simple setup, no network configuration
- ✅ Automatic process management
- ✅ Secure (no network exposure)
- ❌ Single client per server instance
- ❌ Client and server must be on same machine

**Use cases:** Claude Desktop, local CLI tools, personal development

#### 2. **HTTP/SSE Transport (Future)**

HTTP server with Server-Sent Events for remote access. Best for team environments and production deployments.

```bash
# Will be available in future version
python cnpg_mcp_server.py --transport http --host 0.0.0.0 --port 3000
```

**When implemented, will provide:**
- ✅ Multiple clients can connect
- ✅ Remote access capability
- ✅ Independent server lifecycle
- ✅ Better for team/production use
- ⚠️ Requires authentication/TLS setup

**Use cases:** Team-shared server, production deployments, Kubernetes services

The codebase is structured to easily add HTTP transport when needed. See the `run_http_transport()` function for implementation guidelines.

### Kubernetes Configuration

The server uses your kubeconfig for authentication:

- **Local development**: Uses `~/.kube/config`
- **In-cluster**: Automatically uses service account tokens

You can also set the `KUBECONFIG` environment variable:
```bash
export KUBECONFIG=/path/to/your/kubeconfig
```

## Running the Server

### Command-Line Options

```bash
# View all available options
python cnpg_mcp_server.py --help

# Run with stdio transport (default)
python cnpg_mcp_server.py

# Explicitly specify transport mode
python cnpg_mcp_server.py --transport stdio

# Run with HTTP transport (when implemented)
python cnpg_mcp_server.py --transport http --host 0.0.0.0 --port 3000
```

### Standalone Mode (for testing)

```bash
python cnpg_mcp_server.py
```

**Note**: The server runs as a long-running process waiting for MCP requests. In stdio mode, it won't exit until interrupted. This is expected behavior.

### With Claude Desktop

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "cloudnative-pg": {
      "command": "python",
      "args": ["/path/to/cnpg_mcp_server.py"],
      "env": {
        "KUBECONFIG": "/path/to/.kube/config"
      }
    }
  }
}
```

### With Docker/Kubernetes Deployment

For production deployments, you can containerize the server:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cnpg_mcp_server.py .

CMD ["python", "cnpg_mcp_server.py"]
```

Deploy as a Kubernetes service that can be accessed by your LLM application.

## Available Tools

### 1. list_postgres_clusters

List all PostgreSQL clusters in the Kubernetes cluster.

**Parameters:**
- `namespace` (optional): Filter by namespace, or omit for all namespaces
- `detail_level`: "concise" (default) or "detailed"

**Example:**
```
List all PostgreSQL clusters in production namespace
```

### 2. get_cluster_status

Get detailed status for a specific cluster.

**Parameters:**
- `namespace` (required): Namespace of the cluster
- `name` (required): Name of the cluster
- `detail_level`: "concise" (default) or "detailed"

**Example:**
```
Get detailed status for the main-db cluster in production namespace
```

### 3. create_postgres_cluster

Create a new PostgreSQL cluster with high availability.

**Parameters:**
- `namespace` (required): Target namespace
- `name` (required): Cluster name
- `instances` (default: 3): Number of PostgreSQL instances
- `storage_size` (default: "10Gi"): Storage per instance
- `postgres_version` (default: "16"): PostgreSQL version
- `storage_class` (optional): Kubernetes storage class

**Example:**
```
Create a new PostgreSQL cluster named 'app-db' in the production namespace with 5 instances and 100Gi storage
```

### 4. scale_postgres_cluster

Scale a cluster by changing the number of instances.

**Parameters:**
- `namespace` (required): Namespace of the cluster
- `name` (required): Cluster name
- `instances` (required): New number of instances (1-10)

**Example:**
```
Scale the app-db cluster in production to 5 instances
```

## Architecture

### Design Principles

This MCP server follows agent-centric design principles:

1. **Workflow-based tools**: Each tool completes a meaningful workflow, not just a single API call
2. **Optimized for context**: Responses are concise by default, with detailed mode available
3. **Actionable errors**: Error messages suggest next steps
4. **Natural naming**: Tool names reflect user intent, not just API endpoints

### Transport Layer Architecture

The server is designed with **transport-agnostic core logic**, making it easy to add new transport modes without rewriting tool implementations:

```
┌─────────────────────────────────────────────┐
│           MCP Tool Layer                     │
│  (list_clusters, create_cluster, etc.)      │
│  ↓                                           │
│  Core business logic is transport-agnostic  │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│         Transport Layer                      │
│  ┌──────────────┐      ┌─────────────┐      │
│  │ stdio        │      │ HTTP/SSE    │      │
│  │ (current)    │      │ (future)    │      │
│  └──────────────┘      └─────────────┘      │
└─────────────────────────────────────────────┘
```

**Why this matters:**
- All tool functions (decorated with `@mcp.tool()`) work with any transport
- Adding HTTP transport only requires implementing `run_http_transport()`
- No changes needed to business logic when switching transports
- Can run both transports simultaneously if needed

**To add HTTP/SSE transport later:**
1. Uncomment HTTP dependencies in `requirements.txt`
2. Install: `pip install mcp[sse] starlette uvicorn`
3. Implement the `run_http_transport()` function (skeleton already provided)
4. Add authentication/authorization middleware
5. Configure TLS for production

### Components

- **Kubernetes Client**: Uses `kubernetes` Python client for API access
- **CloudNativePG CRDs**: Interacts with Custom Resource Definitions
- **Async operations**: All I/O is async for better performance
- **Error handling**: Comprehensive error formatting with suggestions

## Development

### Adding New Tools

To add a new tool:

1. Create a Pydantic model for input validation
2. Implement the tool function with `@mcp.tool()` decorator
3. Add comprehensive docstring following the format in existing tools
4. Implement error handling with actionable messages
5. Test thoroughly

Example skeleton:

```python
class MyToolInput(BaseModel):
    """Input for my_tool."""
    param1: str = Field(..., description="Description with examples")

@mcp.tool()
async def my_tool(param1: str) -> str:
    """
    Tool description.
    
    Detailed explanation of what this tool does and when to use it.
    
    Args:
        param1: Parameter description with usage guidance
    
    Returns:
        Description of return value format
    
    Examples:
        - Example usage 1
        - Example usage 2
    
    Error Handling:
        - Common error scenarios and how to resolve them
    """
    try:
        # Implementation
        result = await some_async_operation(param1)
        return format_response(result)
    except Exception as e:
        return format_error_message(e, "context description")
```

### Testing

Run syntax check:
```bash
python -m py_compile cnpg_mcp_server.py
```

Test with a real Kubernetes cluster:
```bash
# In one terminal (use tmux to keep it running)
python cnpg_mcp_server.py

# In another terminal, test with MCP client or Claude Desktop
```

### TODO: Upcoming Features

- [ ] Delete cluster tool
- [ ] Backup management (list, create, restore)
- [ ] Log retrieval from pods
- [ ] SQL query execution (with safety guardrails)
- [ ] Database and user management
- [ ] Connection information retrieval
- [ ] Monitoring and metrics integration
- [ ] Certificate and secret management

## Troubleshooting

### "Permission denied" errors

Ensure your service account has the necessary RBAC permissions. Check:
```bash
kubectl auth can-i get clusters.postgresql.cnpg.io --as=system:serviceaccount:default:cnpg-mcp-server
```

### "Connection refused" or "Cluster unreachable"

Verify kubectl connectivity:
```bash
kubectl cluster-info
kubectl get nodes
```

### "No module named 'mcp'"

Install dependencies:
```bash
pip install -r requirements.txt
```

### Server hangs

This is expected behavior - the server waits for MCP requests over stdio. Run in background or use process manager.

## Security Considerations

1. **RBAC**: Apply principle of least privilege - only grant necessary permissions
2. **Secrets**: Never log or expose database credentials
3. **Input validation**: All inputs are validated with Pydantic models
4. **Namespace isolation**: Consider restricting to specific namespaces
5. **Audit logging**: Enable Kubernetes audit logs for compliance

## Resources

- [CloudNativePG Documentation](https://cloudnative-pg.io/documentation/current/)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [Kubernetes Python Client](https://github.com/kubernetes-client/python)

## License

[Your License Here]

## Contributing

Contributions are welcome! Please:

1. Follow the existing code style
2. Add comprehensive docstrings
3. Include error handling
4. Test with real Kubernetes clusters
5. Update README with new features
