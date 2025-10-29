# CloudNativePG MCP Server

An MCP (Model Context Protocol) server for managing PostgreSQL clusters using the [CloudNativePG](https://cloudnative-pg.io/) operator in Kubernetes.

## Overview

This MCP server enables LLMs to interact with PostgreSQL clusters managed by the CloudNativePG operator. It provides high-level workflow tools for:

- 📋 Listing and discovering PostgreSQL clusters
- 🔍 Getting detailed cluster status and health information
- 🚀 Creating new PostgreSQL clusters with best practices
- 📈 Scaling clusters up or down
- 🗑️ Deleting PostgreSQL clusters with safety confirmations
- 👥 Managing PostgreSQL roles/users (list, create, update, delete)
- 🗄️ Managing PostgreSQL databases (list, create, delete)
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

The MCP server needs permissions to interact with CloudNativePG resources. The CloudNativePG helm chart automatically creates ClusterRoles (`cnpg-cloudnative-pg-edit`, `cnpg-cloudnative-pg-view`), so you only need to create a ServiceAccount and bind it to these existing roles:

```bash
# Apply the RBAC configuration (ServiceAccount + RoleBindings)
kubectl apply -f rbac.yaml
```

This creates:
- A `cnpg-mcp-server` ServiceAccount
- ClusterRoleBinding to `cnpg-cloudnative-pg-edit` (for managing clusters)
- ClusterRoleBinding to `view` (for reading pods, events, logs)

Verify the setup:
```bash
# Check the service account was created
kubectl get serviceaccount cnpg-mcp-server

# Verify permissions
kubectl auth can-i get clusters.postgresql.cnpg.io --as=system:serviceaccount:default:cnpg-mcp-server
kubectl auth can-i create clusters.postgresql.cnpg.io --as=system:serviceaccount:default:cnpg-mcp-server
```

**For read-only access:** Change `cnpg-cloudnative-pg-edit` to `cnpg-cloudnative-pg-view` in rbac.yaml

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

**Namespace Handling:**
- Most tools accept an optional `namespace` parameter
- If not specified, the server automatically uses the current namespace from your Kubernetes context
- This makes it easier to work with a default namespace without specifying it every time
- You can check your current namespace with: `kubectl config view --minify -o jsonpath='{..namespace}'`

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

**Enhanced Output Formats:** 4 tools support optional JSON format for programmatic consumption:
- `list_postgres_clusters(format="json")` - Structured cluster list
- `get_cluster_status(format="json")` - Structured cluster details
- `list_postgres_roles(format="json")` - Structured role list
- `list_postgres_databases(format="json")` - Structured database list

All other tools return human-readable text optimized for LLM consumption.

---

### Cluster Management

#### 1. list_postgres_clusters

List all PostgreSQL clusters in the Kubernetes cluster.

**Parameters:**
- `namespace` (optional): Filter by namespace. If not provided, uses the current namespace from your Kubernetes context
- `detail_level`: "concise" (default) or "detailed"
- `format`: "text" (default) or "json" - Output format for programmatic consumption

**Example:**
```
List all PostgreSQL clusters in production namespace
```

**JSON Output:**
When `format="json"`, returns structured data like:
```json
{
  "clusters": [...],
  "count": 3,
  "scope": "namespace 'production'"
}
```

#### 2. get_cluster_status

Get detailed status for a specific cluster.

**Parameters:**
- `name` (required): Name of the cluster
- `namespace` (optional): Namespace of the cluster. If not specified, uses the current namespace from your Kubernetes context
- `detail_level`: "concise" (default) or "detailed"
- `format`: "text" (default) or "json" - Output format for programmatic consumption

**Example:**
```
Get detailed status for the main-db cluster in production namespace
```

**Note:** Supports JSON format for structured output.

#### 3. create_postgres_cluster

Create a new PostgreSQL cluster with high availability.

**Parameters:**
- `name` (required): Cluster name
- `instances` (default: 3): Number of PostgreSQL instances
- `storage_size` (default: "10Gi"): Storage per instance
- `postgres_version` (default: "16"): PostgreSQL version
- `storage_class` (optional): Kubernetes storage class
- `wait` (default: False): Wait for the cluster to become operational before returning
- `timeout` (optional): Maximum time in seconds to wait (30-600 seconds). Defaults to 60 seconds per instance
- `namespace` (optional): Target namespace. If not specified, uses the current namespace from your Kubernetes context
- `dry_run` (default: False): Preview the cluster configuration without creating it

**Example:**
```
Create a new PostgreSQL cluster named 'app-db' in the production namespace with 5 instances and 100Gi storage
```

#### 4. scale_postgres_cluster

Scale a cluster by changing the number of instances.

**Parameters:**
- `name` (required): Cluster name
- `instances` (required): New number of instances (1-10)
- `namespace` (optional): Namespace of the cluster. If not specified, uses the current namespace from your Kubernetes context

**Example:**
```
Scale the app-db cluster in production to 5 instances
```

#### 5. delete_postgres_cluster

Delete a PostgreSQL cluster and its associated resources.

**Automatically cleans up:**
- The cluster resource itself
- All associated role password secrets (using label selector `cnpg.io/cluster={name}`)

**Parameters:**
- `name` (required): Name of the cluster to delete
- `confirm_deletion` (default: False): Must be explicitly set to true to confirm deletion
- `namespace` (optional): Namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context

**Example:**
```
Delete the old-test-cluster with confirmation
```

**Warning:** This is a DESTRUCTIVE operation that permanently removes the cluster and all its data. The tool will report how many secrets were cleaned up.

### Role/User Management

#### 6. list_postgres_roles

List all PostgreSQL roles/users managed in a cluster.

**Parameters:**
- `cluster_name` (required): Name of the PostgreSQL cluster
- `namespace` (optional): Namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context
- `format`: "text" (default) or "json" - Output format for programmatic consumption

**Example:**
```
List all roles in the main-db cluster
```

**Note:** Supports JSON format for structured output with role attributes.

#### 7. create_postgres_role

Create a new PostgreSQL role/user in a cluster. Automatically generates a secure password and stores it in a Kubernetes secret.

**Parameters:**
- `cluster_name` (required): Name of the PostgreSQL cluster
- `role_name` (required): Name of the role to create
- `login` (default: true): Allow role to log in
- `superuser` (default: false): Grant superuser privileges
- `inherit` (default: true): Inherit privileges from parent roles
- `createdb` (default: false): Allow creating databases
- `createrole` (default: false): Allow creating roles
- `replication` (default: false): Allow streaming replication
- `namespace` (optional): Namespace where the cluster exists

**Example:**
```
Create a new role 'app_user' in the main-db cluster with login and createdb privileges
```

#### 8. update_postgres_role

Update attributes of an existing PostgreSQL role/user.

**Parameters:**
- `cluster_name` (required): Name of the PostgreSQL cluster
- `role_name` (required): Name of the role to update
- `login`, `superuser`, `inherit`, `createdb`, `createrole`, `replication` (all optional): Attributes to update
- `password` (optional): New password for the role
- `namespace` (optional): Namespace where the cluster exists

**Example:**
```
Grant createdb privilege to app_user in the main-db cluster
```

#### 9. delete_postgres_role

Delete a PostgreSQL role/user from a cluster. Also deletes the associated Kubernetes secret.

**Parameters:**
- `cluster_name` (required): Name of the PostgreSQL cluster
- `role_name` (required): Name of the role to delete
- `namespace` (optional): Namespace where the cluster exists

**Example:**
```
Delete the old_user role from the main-db cluster
```

### Database Management

#### 10. list_postgres_databases

List all PostgreSQL databases managed by Database CRDs for a cluster.

**Parameters:**
- `cluster_name` (required): Name of the PostgreSQL cluster
- `namespace` (optional): Namespace where the cluster exists
- `format`: "text" (default) or "json" - Output format for programmatic consumption

**Example:**
```
List all databases in the main-db cluster
```

**Note:** Supports JSON format for structured output with database details.

#### 11. create_postgres_database

Create a new PostgreSQL database using CloudNativePG's Database CRD.

**Parameters:**
- `cluster_name` (required): Name of the PostgreSQL cluster
- `database_name` (required): Name of the database to create
- `owner` (required): Name of the role that will own the database
- `reclaim_policy` (default: "retain"): Policy for database deletion ("retain" or "delete")
- `namespace` (optional): Namespace where the cluster exists

**Example:**
```
Create a new database 'app_data' owned by 'app_user' in the main-db cluster
```

#### 12. delete_postgres_database

Delete a PostgreSQL database by removing its Database CRD.

**Parameters:**
- `cluster_name` (required): Name of the PostgreSQL cluster
- `database_name` (required): Name of the database to delete
- `namespace` (optional): Namespace where the cluster exists

**Example:**
```
Delete the old_data database from the main-db cluster
```

**Note:** Whether the database is actually dropped from PostgreSQL depends on the `databaseReclaimPolicy` set when the database was created.

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
- **CloudNativePG CRDs**: Interacts with Custom Resource Definitions:
  - `Cluster`: Primary resource for PostgreSQL cluster management
  - `Database`: Declarative database creation and management (CNPG v1.23+)
- **Declarative Role Management**: Manages PostgreSQL roles through the Cluster CRD's `.spec.managed.roles` field
- **Secret Management**: Automatically creates and manages Kubernetes secrets for role passwords
- **Async operations**: All I/O is async for better performance
- **Lazy initialization**: Kubernetes clients are initialized on first use, allowing graceful startup
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

### Implemented Features

- [x] Delete cluster tool with safety confirmations
- [x] PostgreSQL role/user management (list, create, update, delete)
- [x] PostgreSQL database management (list, create, delete)
- [x] Dry-run mode for cluster creation
- [x] Wait for cluster readiness with configurable timeout
- [x] Automatic namespace inference from Kubernetes context
- [x] Lazy Kubernetes client initialization

### TODO: Upcoming Features

- [ ] Backup management (list, create, restore)
- [ ] Log retrieval from pods
- [ ] SQL query execution (with safety guardrails)
- [ ] Connection information retrieval (automatic secret decoding)
- [ ] Monitoring and metrics integration
- [ ] Certificate and secret management
- [ ] Cluster configuration updates
- [ ] Pooler management

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
   - Use `cnpg-cloudnative-pg-view` for read-only access
   - Use `cnpg-cloudnative-pg-edit` for cluster management
   - Grant additional permissions for secrets if using role management:
     - `list` secrets with label selector (for cleanup during cluster deletion)
     - `create` and `delete` secrets (for role management)
2. **Secrets**: Never log or expose database credentials
   - Role passwords are automatically generated and stored in Kubernetes secrets
   - Secrets are labeled with cluster and role information for easy management
   - Secrets are named `cnpg-{cluster}-user-{role}` to avoid conflicts
   - **Automatic cleanup**: Secrets are automatically deleted when their cluster is deleted
3. **Input validation**: All inputs are validated with Pydantic models
4. **Namespace isolation**: Consider restricting to specific namespaces
5. **Audit logging**: Enable Kubernetes audit logs for compliance
6. **Destructive operations**: Cluster and database deletion require explicit confirmation
7. **Role privileges**: Be cautious when granting superuser or replication privileges
8. **Database reclaim policy**: Choose "retain" for production databases to prevent accidental data loss

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
