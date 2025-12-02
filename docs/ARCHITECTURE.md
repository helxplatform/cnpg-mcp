# CNPG MCP Server - Complete Architecture Documentation

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Principles](#architecture-principles)
3. [Component Architecture](#component-architecture)
4. [Deployment Architecture](#deployment-architecture)
5. [Authentication Architecture](#authentication-architecture)
6. [Data Flow](#data-flow)
7. [Component Deep Dive](#component-deep-dive)
8. [Configuration Management](#configuration-management)
9. [Scalability and Operations](#scalability-and-operations)

---

## System Overview

The CloudNativePG MCP Server is a **production-grade Model Context Protocol (MCP) server** that enables Large Language Models (LLMs) to manage PostgreSQL clusters in Kubernetes using the CloudNativePG operator.

### Purpose

- **Enable LLM-driven database operations**: Allow AI assistants like Claude to perform database lifecycle management through natural language
- **CloudNativePG integration**: Provide a bridge between MCP protocol and CloudNativePG Custom Resources
- **Multi-environment support**: Support both local development (Claude Desktop) and production deployments (Kubernetes)
- **Dual authentication**: Support both FastMCP OAuth Proxy (production) and standard OIDC (testing)

### Key Capabilities

The server exposes **12 MCP tools** organized into three categories:

**Cluster Management (5 tools)**:
1. `list_postgres_clusters` - List all PostgreSQL clusters
2. `get_cluster_status` - Get detailed cluster status
3. `create_postgres_cluster` - Create new cluster with HA
4. `scale_postgres_cluster` - Scale cluster instances
5. `delete_postgres_cluster` - Delete cluster with safety checks

**Role/User Management (4 tools)**:
6. `list_postgres_roles` - List roles in a cluster
7. `create_postgres_role` - Create role with auto-generated password
8. `update_postgres_role` - Update role attributes
9. `delete_postgres_role` - Delete role and secrets

**Database Management (3 tools)**:
10. `list_postgres_databases` - List databases via CRDs
11. `create_postgres_database` - Create database with reclaim policy
12. `delete_postgres_database` - Delete Database CRD

---

## Architecture Principles

### 1. Transport-Agnostic Design

```
MCP Tools Layer (Business Logic)
        ↓
Transport Layer (stdio or HTTP/SSE)
        ↓
Kubernetes API
        ↓
CloudNativePG Operator
```

**Key Decisions**:
- Tools are pure async functions, no transport coupling
- Transport selection happens at startup
- Same tool code works for stdio (Claude Desktop) and HTTP (production)

### 2. Shared Tool Library Pattern

All tool implementations live in a **single shared module** (`src/cnpg_tools.py`), imported by both servers:

```python
# Main server
from cnpg_tools import list_postgres_clusters
@mcp.tool()
async def list_postgres_clusters_tool(...):
    return await list_postgres_clusters(...)

# Test server (same tools)
from cnpg_tools import list_postgres_clusters
@mcp2.tool()
async def list_postgres_clusters_tool(...):
    return await list_postgres_clusters(...)
```

**Benefits**:
- Single source of truth for business logic
- Zero code duplication
- Changes propagate to both endpoints automatically
- Easy to test tools in isolation

### 3. Kubernetes Sidecar Pattern for Dual Authentication

Instead of complex routing within a single process, we use **two separate server processes** in a Kubernetes sidecar deployment:

```
┌─────────────────────────────────────────────────────────┐
│ Pod: cnpg-mcp-server                                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────────────────┐  ┌────────────────────┐  │
│  │ Container 1: Main        │  │ Container 2: Test  │  │
│  │ Port: 4204               │  │ Port: 3001         │  │
│  │ Auth: FastMCP OAuth      │  │ Auth: OIDC JWT     │  │
│  │ Tools: Import cnpg_tools │  │ Tools: Same import │  │
│  └──────────────────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Why Sidecar?**:
- **OAuth Standards Compliance**: OAuth discovery endpoints naturally at root on main server
- **Complete Separation**: No authentication bleeding or routing conflicts
- **Feature Flag**: Easy to disable test endpoint via Helm values
- **Standard Pattern**: Well-understood Kubernetes deployment pattern
- See [SIDECAR_ARCHITECTURE.md](SIDECAR_ARCHITECTURE.md) for full decision rationale

### 4. Configuration as Code

**Three-tier configuration hierarchy**:

1. **make.env**: Build configuration (registry, image names, tags)
2. **auth0-config.json**: Auth0 setup (domain, clients, secrets)
3. **auth0-values.yaml**: Helm deployment values (derived from above)

**Automation**:
- `bin/setup-auth0.py`: Idempotent Auth0 setup + values file generation
- `bin/create_secrets.py`: Kubernetes secret creation from config
- `Makefile`: Build, push, deploy orchestration

---

## Component Architecture

### Three-Tier Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Layer 1: Tools                       │
│                  (cnpg_tools.py)                        │
│  - 12 tool implementations                              │
│  - Kubernetes client management                         │
│  - Business logic and validation                        │
│  - Error handling and formatting                        │
└─────────────────────────────────────────────────────────┘
                        ↑
        ┌───────────────┴───────────────┐
        │                               │
┌───────────────────┐         ┌───────────────────┐
│   Layer 2: Main   │         │  Layer 2: Test    │
│   Server          │         │  Server           │
│ (cnpg_mcp_        │         │ (cnpg_mcp_test_   │
│  server.py)       │         │  server.py)       │
│                   │         │                   │
│ - FastMCP init    │         │ - FastMCP init    │
│ - Tool decorators │         │ - Tool decorators │
│ - OAuth proxy     │         │ - OIDC middleware │
│ - HTTP routes     │         │ - HTTP routes     │
└───────────────────┘         └───────────────────┘
        ↓                               ↓
┌───────────────────────────────────────────────────────┐
│           Layer 3: Kubernetes Deployment              │
│                  (Helm Chart)                         │
│ - Deployment (sidecar containers)                     │
│ - Service (dual ports)                                │
│ - Ingress (path-based routing)                        │
│ - ConfigMap (OIDC config)                             │
│ - Secret (Auth0 credentials)                          │
└───────────────────────────────────────────────────────┘
```

---

## Deployment Architecture

### Kubernetes Resources

#### 1. Deployment (Sidecar Pattern)

**File**: `chart/templates/deployment.yaml`

```yaml
spec:
  template:
    spec:
      containers:
      # Main container - FastMCP OAuth
      - name: cnpg-mcp
        image: wateim/cnpg-mcp:v1.2.0
        ports:
        - containerPort: 4204
          name: http
        volumeMounts:
        - name: oidc-config        # ConfigMap
          mountPath: /etc/mcp
        - name: auth0-credentials  # Secret
          mountPath: /etc/mcp/secrets

      # Test sidecar - OIDC (optional, controlled by testSidecar.enabled)
      - name: cnpg-mcp-test
        image: wateim/cnpg-mcp-test-server:v1.2.0
        command: ["python", "cnpg_mcp_test_server.py"]
        args: ["--port", "3001"]
        ports:
        - containerPort: 3001
          name: http-test
        volumeMounts:
        - name: oidc-config        # Shared ConfigMap
          mountPath: /etc/mcp
        - name: auth0-credentials  # Shared Secret
          mountPath: /etc/mcp/secrets
```

**Key Points**:
- Both containers share the same volumes (ConfigMap, Secret)
- Test sidecar is optional via Helm flag
- Different entry points but same base image
- Independent health checks for each container

#### 2. Service (Dual Ports)

**File**: `chart/templates/service.yaml`

```yaml
spec:
  type: ClusterIP
  ports:
  - port: 4204              # Main server
    targetPort: http
    name: http
  - port: 3001              # Test server (conditional)
    targetPort: http-test
    name: http-test
  selector:
    app.kubernetes.io/name: cnpg-mcp
```

**Key Points**:
- Single service with multiple ports
- Both containers selected by same label
- Test port only exposed if sidecar enabled

#### 3. Ingress (Path-Based Routing)

**File**: `chart/templates/ingress.yaml`

```yaml
spec:
  rules:
  - host: claude-cnpg.wat.im
    http:
      paths:
      # Test endpoint (if enabled) - MUST come first for prefix matching
      - path: /test
        pathType: Prefix
        backend:
          service:
            name: cnpg-mcp
            port:
              number: 3001  # Test sidecar

      # Main endpoint - catches all other paths
      - path: /
        pathType: Prefix
        backend:
          service:
            name: cnpg-mcp
            port:
              number: 4204  # Main server
```

**Key Points**:
- Test endpoint MUST be first in path list (more specific prefix)
- Main endpoint at root catches OAuth endpoints (`/register`, `/.well-known/...`)
- Single hostname for both endpoints
- TLS termination at Ingress

#### 4. ConfigMap (OIDC Configuration)

**File**: `chart/templates/configmap.yaml`

```yaml
data:
  oidc.yaml: |
    # Auth0 Configuration
    issuer: "https://dev-15i-ae3b.auth0.com"
    audience: "https://claude-cnpg.wat.im/mcp"
    client_id: "ZUKLpJLJYsBXS7dXW4hd71Z7e9bKfgEg"

    # Secret reference (mounted from Kubernetes Secret)
    client_secret_file: "/etc/mcp/secrets/server-client-secret"

    # Public URL (derived from Ingress)
    public_url: "https://claude-cnpg.wat.im"
```

**Key Points**:
- Non-sensitive configuration only
- Shared between both containers
- Auto-generated from Helm values
- YAML format for easy parsing

#### 5. Secret (Auth0 Credentials)

**Created by**: `bin/create_secrets.py`

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: mcp-server-auth0-credentials  # Derived from release name
type: Opaque
data:
  server-client-secret: <base64>  # For FastMCP OAuth
  mgmt-client-secret: <base64>    # For management scripts
  mgmt-client-id: <base64>        # For management scripts
  auth0-domain: <base64>          # For management scripts
  connection-id: <base64>         # For management scripts
```

**Key Points**:
- Managed separately from Helm (create before deployment)
- Name derived from Helm release name: `{{ .Release.Name }}-auth0-credentials`
- Contains both server secrets and management API credentials
- Created from `auth0-config.json` via `create_secrets.py`

---

## Authentication Architecture

### Dual Authentication Strategy

The system supports **two authentication methods** to serve different use cases:

| Aspect | Main Server (FastMCP OAuth) | Test Server (OIDC) |
|--------|----------------------------|-------------------|
| **Port** | 4204 | 3001 |
| **Path** | `/` (all paths except `/test`) | `/test` |
| **Auth Method** | OAuth 2.0 with token issuance | Standard OIDC JWT validation |
| **Token Flow** | Auth0 → MCP server → Issues MCP token | Auth0 → Direct JWT validation |
| **Client Token** | MCP-signed JWT (HS256) | Auth0 JWT |
| **Use Case** | Production (Claude.ai) | Testing and development |
| **DCR Support** | Yes (built-in proxy) | No |
| **Consent Screen** | Yes | No |

### Authentication Flow - Main Server (FastMCP OAuth)

**Sequence Diagram**:

```
┌──────┐         ┌──────────┐         ┌──────┐         ┌─────────┐
│Client│         │MCP Server│         │Auth0 │         │Resource │
│      │         │(OAuth)   │         │      │         │ (Tools) │
└──┬───┘         └────┬─────┘         └───┬──┘         └────┬────┘
   │                  │                   │                  │
   │ 1. GET /.well-known/oauth-authorization-server        │
   ├─────────────────>│                   │                  │
   │ 2. OAuth metadata│                   │                  │
   │<─────────────────┤                   │                  │
   │                  │                   │                  │
   │ 3. GET /authorize + PKCE             │                  │
   ├─────────────────>│                   │                  │
   │ 4. Redirect to Auth0                 │                  │
   │<─────────────────┤                   │                  │
   │                  │                   │                  │
   │ 5. User authenticates                │                  │
   ├────────────────────────────────────>│                  │
   │ 6. Redirect with auth code           │                  │
   │<─────────────────────────────────────┤                  │
   │                  │                   │                  │
   │ 7. POST /token + code + PKCE         │                  │
   ├─────────────────>│                   │                  │
   │                  │ 8. Exchange code for Auth0 token    │
   │                  ├──────────────────>│                  │
   │                  │ 9. Auth0 JWT (internal)             │
   │                  │<──────────────────┤                  │
   │                  │ 10. Store Auth0 token in session    │
   │                  │     (encrypted with Fernet)          │
   │                  │ 11. Issue MCP token (signed HS256)  │
   │ 12. MCP JWT      │                   │                  │
   │<─────────────────┤                   │                  │
   │                  │                   │                  │
   │ 13. POST /mcp (with MCP token)       │                  │
   ├─────────────────>│                   │                  │
   │                  │ 14. Validate MCP token              │
   │                  │ 15. Look up Auth0 session           │
   │                  │ 16. Execute tool  │                  │
   │                  ├──────────────────────────────────────>│
   │                  │ 17. Result        │                  │
   │                  │<──────────────────────────────────────┤
   │ 18. Response     │                   │                  │
   │<─────────────────┤                   │                  │
```

**Key Points**:
1. **Discovery**: Client gets OAuth endpoints from `.well-known/oauth-authorization-server`
2. **PKCE**: Client generates `code_verifier` and `code_challenge` for security
3. **Authorization**: User authenticates with Auth0, server gets authorization code
4. **Token Exchange**: Server exchanges code for Auth0 token (internal, encrypted storage)
5. **Token Issuance**: Server issues its own MCP-signed JWT to client
6. **Validation**: For each request, server validates MCP token and looks up stored Auth0 session

**Implementation**: See `src/auth_fastmcp.py` (FastMCP OAuth Proxy wrapper)

### Authentication Flow - Test Server (OIDC)

**Sequence Diagram**:

```
┌──────┐         ┌──────────┐         ┌──────┐         ┌─────────┐
│Client│         │MCP Server│         │Auth0 │         │Resource │
│      │         │ (OIDC)   │         │      │         │ (Tools) │
└──┬───┘         └────┬─────┘         └───┬──┘         └────┬────┘
   │                  │                   │                  │
   │ 1. User gets token directly from Auth0 (external)      │
   ├────────────────────────────────────>│                  │
   │ 2. Auth0 JWT     │                   │                  │
   │<─────────────────────────────────────┤                  │
   │                  │                   │                  │
   │ 3. POST /test (with Auth0 JWT)       │                  │
   ├─────────────────>│                   │                  │
   │                  │ 4. Fetch JWKS     │                  │
   │                  ├──────────────────>│                  │
   │                  │ 5. Public keys    │                  │
   │                  │<──────────────────┤                  │
   │                  │ 6. Validate JWT (issuer, audience, signature)
   │                  │ 7. Execute tool   │                  │
   │                  ├──────────────────────────────────────>│
   │                  │ 8. Result         │                  │
   │                  │<──────────────────────────────────────┤
   │ 9. Response      │                   │                  │
   │<─────────────────┤                   │                  │
```

**Key Points**:
1. **No OAuth Flow**: Client obtains Auth0 token directly (e.g., via `test/get-user-token.py`)
2. **Direct Validation**: Server validates Auth0 JWT using JWKS public keys
3. **No Token Issuance**: No MCP token layer, Auth0 token used directly
4. **Stateless**: No session storage needed

**Implementation**: See `src/auth_oidc.py` (OIDC middleware)

### Why Two Authentication Methods?

| Requirement | Main (OAuth) | Test (OIDC) |
|------------|--------------|-------------|
| **MCP Spec Compliance** | ✅ Server issues tokens | ❌ Uses Auth0 tokens |
| **Production Ready** | ✅ Consent, CSRF protection | ⚠️ No consent flow |
| **Claude.ai Compatible** | ✅ Solves JWE problem | ❌ Would receive JWE |
| **Testing Simplicity** | ❌ Complex OAuth flow | ✅ Simple token flow |
| **Port-Forward Friendly** | ❌ Needs public callback | ✅ Works with port-forward |
| **Debug Visibility** | ❌ Encrypted session storage | ✅ Direct token inspection |

**Design Decision**: Separate servers allows both methods to coexist without compromise. Production uses OAuth (MCP compliant), testing uses OIDC (simple debugging).

---

## Data Flow

### Request Flow - Main Server

```
1. Claude.ai Client
   ↓
2. Ingress (TLS termination)
   ├─ Host: claude-cnpg.wat.im
   └─ Path: / (or /register, /.well-known/...)
   ↓
3. Kubernetes Service (port 4204)
   ↓
4. Main Container (cnpg_mcp_server.py)
   ├─ FastMCP OAuth Proxy
   │  ├─ Validate MCP token
   │  ├─ Look up Auth0 session
   │  └─ Decrypt Auth0 token
   ↓
5. MCP Tool Router
   ├─ Parse MCP request
   ├─ Validate tool name
   └─ Extract parameters
   ↓
6. Tool Implementation (cnpg_tools.py)
   ├─ Validate inputs (Pydantic)
   ├─ Initialize Kubernetes clients
   ├─ Call Kubernetes API
   │  ├─ CustomObjectsApi (for CNPG resources)
   │  └─ CoreV1Api (for Secrets, Pods)
   ↓
7. CloudNativePG Operator
   ├─ Reconcile Cluster CRD
   ├─ Create/Update PostgreSQL instances
   └─ Manage HA, backups, etc.
   ↓
8. Response Path (reverse)
   ├─ Tool formats response (markdown)
   ├─ Truncate to CHARACTER_LIMIT (25000)
   ├─ Return via MCP protocol
   └─ Client receives result
```

### Request Flow - Test Server

```
1. Test Client (test-mcp.py)
   ↓
2. Ingress (TLS termination)
   ├─ Host: claude-cnpg.wat.im
   └─ Path: /test
   ↓
3. Kubernetes Service (port 3001)
   ↓
4. Test Container (cnpg_mcp_test_server.py)
   ├─ OIDC Middleware
   │  ├─ Extract Bearer token
   │  ├─ Fetch JWKS from Auth0
   │  ├─ Validate JWT (issuer, audience, signature, expiry)
   │  └─ Attach user info to request
   ↓
5. MCP Tool Router (same as main)
   ↓
6. Tool Implementation (same as main - cnpg_tools.py)
   ↓
7. CloudNativePG Operator (same as main)
   ↓
8. Response Path (same as main)
```

**Key Difference**: Authentication middleware only. Tools and Kubernetes interaction are identical.

---

## Component Deep Dive

### 1. Shared Tools Library (`src/cnpg_tools.py`)

**Purpose**: Single source of truth for all MCP tool implementations and Kubernetes client management.

**Structure** (~1,200 lines):

```python
# Lines 1-80: Imports, logging, filters
# Lines 81-100: Configuration constants
# Lines 101-120: Kubernetes client initialization
# Lines 121-250: Utility functions
# Lines 251-1200: 12 tool implementations
```

**Key Functions**:

```python
# Kubernetes client initialization (lazy)
def get_kubernetes_clients() -> Tuple[client.CustomObjectsApi, client.CoreV1Api]:
    """Initialize Kubernetes clients (in-cluster or kubeconfig)."""
    global custom_api, core_api, _k8s_init_attempted, _k8s_init_error

    if _k8s_init_attempted:
        if _k8s_init_error:
            raise RuntimeError(f"Kubernetes initialization failed: {_k8s_init_error}")
        return custom_api, core_api

    try:
        # Try in-cluster first
        config.load_incluster_config()
    except:
        # Fall back to kubeconfig
        config.load_kube_config()

    custom_api = client.CustomObjectsApi()
    core_api = client.CoreV1Api()
    _k8s_init_attempted = True
    return custom_api, core_api

# Tool implementation example
async def create_postgres_cluster(
    name: str,
    instances: int = 3,
    storage_size: str = "1Gi",
    postgres_version: str = "16",
    namespace: str = None,
    dry_run: bool = False
) -> str:
    """Create a new PostgreSQL cluster with high availability."""
    try:
        custom_api, _ = get_kubernetes_clients()
        namespace = namespace or get_current_namespace()

        # Build cluster manifest
        cluster_manifest = {
            "apiVersion": f"{CNPG_GROUP}/{CNPG_VERSION}",
            "kind": "Cluster",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "instances": instances,
                "storage": {"size": storage_size},
                "imageName": f"ghcr.io/cloudnative-pg/postgresql:{postgres_version}"
            }
        }

        if dry_run:
            return format_dry_run_output(cluster_manifest)

        # Create cluster via Kubernetes API
        result = await asyncio.to_thread(
            custom_api.create_namespaced_custom_object,
            group=CNPG_GROUP,
            version=CNPG_VERSION,
            namespace=namespace,
            plural=CNPG_PLURAL,
            body=cluster_manifest
        )

        return format_success_message(result)

    except Exception as e:
        return format_error_message(e, "cluster creation")
```

**Key Patterns**:
- **Lazy Initialization**: Kubernetes clients initialized on first use
- **Async Wrappers**: Sync Kubernetes API calls wrapped with `asyncio.to_thread()`
- **Error Handling**: All tools use try/except with `format_error_message()`
- **Response Truncation**: All responses pass through `truncate_response()`
- **Namespace Handling**: Auto-detect current namespace if not specified

### 2. Main Server (`src/cnpg_mcp_server.py`)

**Purpose**: Production MCP server with FastMCP OAuth proxy for token issuance.

**Structure** (~400 lines):

```python
# Lines 1-60: Imports, logging configuration
# Lines 61-65: FastMCP initialization
# Lines 66-250: Tool decorators (wrap cnpg_tools functions)
# Lines 251-350: Health/readiness endpoints
# Lines 351-380: CLI argument parsing
# Lines 381-400: Main entry point (stdio or HTTP transport)
```

**FastMCP Integration**:

```python
from fastmcp import FastMCP

# Initialize FastMCP
mcp = FastMCP("cloudnative-pg")

# Register tools (wrapping shared implementations)
@mcp.tool(name="list_postgres_clusters")
async def list_postgres_clusters_tool(
    namespace: str = None,
    all_namespaces: bool = False,
    detail_level: str = "concise"
):
    """List all PostgreSQL clusters managed by CloudNativePG."""
    return await list_postgres_clusters(namespace, all_namespaces, detail_level)

# ... 11 more tool registrations ...

# Run with OAuth proxy
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--port", type=int, default=4204)
    args = parser.parse_args()

    if args.transport == "stdio":
        # Stdio transport for Claude Desktop
        import asyncio
        asyncio.run(mcp.run_stdio_async())
    else:
        # HTTP transport with OAuth
        from auth_fastmcp import create_auth0_oauth_proxy
        auth_proxy = create_auth0_oauth_proxy()

        uvicorn.run(
            mcp.get_asgi_app(
                auth_provider=auth_proxy,
                additional_routes=[
                    Route("/healthz", healthz),
                    Route("/readyz", readyz)
                ]
            ),
            host="0.0.0.0",
            port=args.port
        )
```

### 3. Test Server (`src/cnpg_mcp_test_server.py`)

**Purpose**: Testing/development MCP server with standard OIDC authentication.

**Structure** (~350 lines):

```python
# Lines 1-60: Imports, logging configuration
# Lines 61-65: FastMCP initialization (separate instance)
# Lines 66-250: Tool decorators (same as main server)
# Lines 251-300: Health/readiness endpoints
# Lines 301-320: OIDC middleware setup
# Lines 321-350: Main entry point (HTTP only)
```

**OIDC Integration**:

```python
from fastmcp import FastMCP
from auth_oidc import OIDCAuthProvider, OIDCAuthMiddleware

# Initialize FastMCP (separate instance)
mcp = FastMCP("cloudnative-pg-test")

# Register tools (same as main server)
@mcp.tool(name="list_postgres_clusters")
async def list_postgres_clusters_tool(...):
    return await list_postgres_clusters(...)

# ... 11 more tool registrations ...

# Run with OIDC middleware
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=3001)
    args = parser.parse_args()

    # Create OIDC auth provider
    oidc_provider = OIDCAuthProvider(config_path="/etc/mcp/oidc.yaml")

    # Get base ASGI app
    app = mcp.get_asgi_app(
        additional_routes=[
            Route("/healthz", healthz),
            Route("/readyz", readyz)
        ]
    )

    # Wrap with OIDC middleware
    app_with_auth = OIDCAuthMiddleware(app, oidc_provider)

    uvicorn.run(app_with_auth, host="0.0.0.0", port=args.port)
```

**Key Differences from Main Server**:
- Different FastMCP instance name (`cloudnative-pg-test` vs `cloudnative-pg`)
- OIDC middleware instead of OAuth proxy
- HTTP only (no stdio mode)
- Different default port (3001 vs 4204)

### 4. FastMCP OAuth Proxy (`src/auth_fastmcp.py`)

**Purpose**: Wrap FastMCP's OAuthProxy for Auth0 integration with MCP token issuance.

**Structure** (~250 lines):

```python
from fastmcp.server.auth import OAuthProxy
from fastmcp.server.auth.providers.jwt import JWTVerifier

def create_auth0_oauth_proxy(config_path: str = "/etc/mcp/oidc.yaml") -> OAuthProxy:
    """Create FastMCP OAuth Proxy configured for Auth0."""

    # Load configuration
    config = load_oidc_config(config_path)
    issuer = config["issuer"]
    audience = config["audience"]
    client_id = config["client_id"]
    client_secret = load_client_secret(config["client_secret_file"])
    public_url = config.get("public_url", "http://localhost:4204")

    # Create JWT verifier (for Auth0 tokens - internal use)
    jwks_uri = config.get("jwks_uri") or f"{issuer}/.well-known/jwks.json"
    token_verifier = JWTVerifier(
        jwks_uri=jwks_uri,
        issuer=issuer,
        audience=audience
    )

    # Create OAuth Proxy
    auth_proxy = OAuthProxy(
        upstream_authorization_endpoint=f"{issuer}/authorize",
        upstream_token_endpoint=f"{issuer}/oauth/token",
        upstream_client_id=client_id,
        upstream_client_secret=client_secret,
        token_verifier=token_verifier,
        base_url=public_url,
        extra_authorize_params={"audience": audience},
        extra_token_params={"audience": audience},
        forward_pkce=True,
        require_authorization_consent=True
    )

    return auth_proxy
```

**What OAuthProxy Does** (FastMCP built-in):
1. **Discovery Endpoints**: Serves `/.well-known/oauth-authorization-server`
2. **Authorization**: Handles `/authorize` with redirect to Auth0
3. **Token Exchange**: Handles `/token` endpoint
   - Exchanges authorization code for Auth0 token
   - Stores Auth0 token in encrypted session (Fernet)
   - Issues MCP-signed JWT token (HS256)
4. **Token Validation**: For each request:
   - Validates MCP token signature
   - Looks up stored Auth0 session
   - Decrypts Auth0 token
5. **PKCE Support**: Validates PKCE challenge/verifier
6. **Consent Screen**: Shows authorization consent UI

**Why This Solves the JWE Problem**:
- Auth0 issues JWE (encrypted) tokens internally
- OAuthProxy decrypts and stores them securely
- Clients receive MCP-signed JWT (not JWE)
- Claude.ai can validate MCP tokens (not Auth0 tokens)

See [FASTMCP_OAUTH_MIGRATION.md](FASTMCP_OAUTH_MIGRATION.md) for migration details.

### 5. OIDC Authentication (`src/auth_oidc.py`)

**Purpose**: Standard OIDC JWT validation for test endpoint (no token issuance).

**Structure** (~300 lines):

```python
class OIDCAuthProvider:
    """OIDC authentication provider with JWKS validation."""

    def __init__(self, config_path: str = "/etc/mcp/oidc.yaml"):
        config = load_oidc_config(config_path)
        self.issuer = config["issuer"]
        self.audience = config["audience"]
        self.jwks_uri = config.get("jwks_uri") or f"{issuer}/.well-known/jwks.json"
        self._jwks_cache = None
        self._jwks_cache_time = 0

    async def fetch_jwks(self) -> Dict[str, Any]:
        """Fetch JWKS from Auth0 (with 1-hour cache)."""
        now = time.time()
        if self._jwks_cache and (now - self._jwks_cache_time) < 3600:
            return self._jwks_cache

        async with httpx.AsyncClient() as client:
            response = await client.get(self.jwks_uri)
            response.raise_for_status()
            self._jwks_cache = response.json()
            self._jwks_cache_time = now
            return self._jwks_cache

    async def validate_token(self, token: str) -> Dict[str, Any]:
        """Validate JWT token."""
        # Fetch JWKS
        jwks = await self.fetch_jwks()

        # Decode header to get key ID
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        # Find matching key
        key = next((k for k in jwks["keys"] if k["kid"] == kid), None)
        if not key:
            raise ValueError("Key not found in JWKS")

        # Verify signature and claims
        payload = jwt.decode(
            token,
            key=jwk.construct(key),
            algorithms=["RS256"],
            issuer=self.issuer,
            audience=self.audience
        )

        return payload

class OIDCAuthMiddleware:
    """Starlette middleware for OIDC authentication."""

    def __init__(self, app, auth_provider: OIDCAuthProvider):
        self.app = app
        self.auth_provider = auth_provider

    async def __call__(self, scope, receive, send):
        # Skip auth for health checks
        if scope["type"] == "http" and scope["path"] in ["/healthz", "/readyz"]:
            return await self.app(scope, receive, send)

        # Extract Bearer token
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()

        if not auth_header.startswith("Bearer "):
            # Return 401
            return await send_401(send)

        token = auth_header[7:]  # Remove "Bearer "

        try:
            # Validate token
            payload = await self.auth_provider.validate_token(token)

            # Attach user info to request state
            scope["state"] = {"user": payload}

            # Continue to app
            return await self.app(scope, receive, send)

        except Exception as e:
            logger.error(f"Token validation failed: {e}")
            return await send_401(send)
```

**Key Points**:
- **Stateless**: No session storage, validates token on every request
- **JWKS Caching**: Caches public keys for 1 hour
- **Standard Flow**: No OAuth dance, just JWT validation
- **Middleware Pattern**: Uses Starlette ASGI middleware

---

## Configuration Management

### Configuration Flow

```
1. Build Configuration (make.env)
   ├─ REGISTRY=wateim
   ├─ IMAGE_NAME=cnpg-mcp
   └─ TAG=cleanup3-294a09f
   ↓
2. Auth0 Setup (bin/setup-auth0.py)
   ├─ Creates Auth0 resources (APIs, clients, connections)
   ├─ Saves auth0-config.json
   └─ Generates auth0-values.yaml (from make.env + config)
   ↓
3. Secret Creation (bin/create_secrets.py)
   ├─ Reads auth0-config.json
   └─ Creates Kubernetes Secret: <release-name>-auth0-credentials
   ↓
4. Helm Deployment
   ├─ Reads auth0-values.yaml
   ├─ References Secret (created in step 3)
   └─ Deploys to Kubernetes
```

### Configuration Files

#### 1. `make.env` (Build Configuration)

**Created by**: `bin/init_make_config.py` or manually

```bash
REGISTRY=wateim
IMAGE_NAME=cnpg-mcp
TAG=cleanup3-294a09f
PLATFORM=linux/amd64
```

**Usage**:
- `Makefile`: Build and push images
- `bin/setup-auth0.py`: Generate Helm values with image tags

#### 2. `auth0-config.json` (Auth0 Setup)

**Created by**: `bin/setup-auth0.py`

```json
{
  "domain": "dev-15i-ae3b.auth0.com",
  "issuer": "https://dev-15i-ae3b.auth0.com",
  "audience": "https://claude-cnpg.wat.im/mcp",
  "connection_id": "con_nv7FMnG6bpS5MJSS",
  "connection_promoted": true,
  "management_api": {
    "client_id": "Ld8VqxvIWQQVV1Es8AnhzzOuTuUyvpjX",
    "client_secret": "BsYAoYx89RyMlXhpTh05DiBapfz7hX6U..."
  },
  "server_client": {
    "client_id": "ZUKLpJLJYsBXS7dXW4hd71Z7e9bKfgEg",
    "client_secret": "hhCAeqZ7-4B_dNv7_sSVVWiH1LGt87ZG..."
  },
  "test_client": {
    "client_id": "chq26RNPuQzoQZ0aYGWS1M0CnRB4WikU"
  }
}
```

**Usage**:
- `bin/setup-auth0.py`: Idempotent re-runs (preserves secrets)
- `bin/create_secrets.py`: Create Kubernetes secrets
- `test/get-user-token.py`: Get test tokens

#### 3. `auth0-values.yaml` (Helm Deployment Values)

**Created by**: `bin/setup-auth0.py`

```yaml
# Container image configuration
image:
  repository: wateim/cnpg-mcp
  pullPolicy: Always  # Dev tag - always pull latest
  tag: "cleanup3-294a09f"  # From make.env

replicaCount: 1

# FastMCP OAuth Proxy Configuration
oidc:
  issuer: "https://dev-15i-ae3b.auth0.com"
  audience: "https://claude-cnpg.wat.im/mcp"
  clientId: "ZUKLpJLJYsBXS7dXW4hd71Z7e9bKfgEg"

# Service configuration
service:
  type: ClusterIP
  port: 4204

# Ingress
ingress:
  enabled: true
  className: "nginx"
  host: claude-cnpg.wat.im
  tls:
    enabled: true

# Test Sidecar Configuration
testSidecar:
  enabled: true
  repository: wateim/cnpg-mcp-test-server
  pullPolicy: Always
  tag: "cleanup3-294a09f"
```

**Usage**:
- `helm install mcp-server ./chart -f auth0-values.yaml`
- Can be regenerated from `auth0-config.json` without Auth0 access

### Setup Workflow

**Initial Setup**:

```bash
# 1. Initialize build configuration
python bin/init_make_config.py

# 2. Setup Auth0 (creates API, clients, config file)
python bin/setup-auth0.py \
    --domain dev-15i-ae3b.auth0.com \
    --api-identifier https://claude-cnpg.wat.im/mcp \
    --token <AUTH0_MGMT_TOKEN>

# 3. Build and push images
make build push

# 4. Create Kubernetes secret
python bin/create_secrets.py \
    --namespace default \
    --release-name mcp-server \
    --replace

# 5. Deploy with Helm
helm install mcp-server ./chart -f auth0-values.yaml
```

**Subsequent Deployments** (after code changes):

```bash
# 1. Update build tag
python bin/init_make_config.py  # Updates TAG in make.env

# 2. Rebuild images
make build push

# 3. Regenerate Helm values (picks up new TAG)
python bin/setup-auth0.py  # No token needed - uses saved config

# 4. Upgrade Helm deployment
helm upgrade mcp-server ./chart -f auth0-values.yaml
```

**Secret Rotation**:

```bash
# 1. Recreate Auth0 clients (generates new secrets)
python bin/setup-auth0.py --recreate-client --token <TOKEN>

# 2. Update Kubernetes secret
python bin/create_secrets.py \
    --namespace default \
    --release-name mcp-server \
    --replace

# 3. Restart pods to pick up new secret
kubectl rollout restart deployment mcp-server
```

---

## Scalability and Operations

### Production Considerations

#### 1. Resource Requirements

**Recommended Resource Limits**:

```yaml
resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "500m"

testSidecar:
  resources:
    requests:
      memory: "128Mi"
      cpu: "50m"
    limits:
      memory: "256Mi"
      cpu: "200m"
```

**Scaling Considerations**:
- **CPU**: Primarily I/O bound (Kubernetes API calls), low CPU usage
- **Memory**: Modest memory footprint (~100-200MB per container)
- **Network**: Moderate (Kubernetes API traffic + MCP requests)

#### 2. High Availability

**Current Limitations**:
- **Session Storage**: OAuth sessions stored in-memory (FastMCP OAuthProxy)
- **Stateful**: Cannot scale horizontally without sticky sessions
- **Single Pod**: Recommended `replicaCount: 1`

**Future Improvements**:
- Implement Redis-backed session storage
- Add session affinity to Ingress (if scaling > 1)
- Consider StatefulSet for stable network identity

#### 3. Monitoring

**Health Checks**:

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: http
  initialDelaySeconds: 10
  periodSeconds: 30
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /readyz
    port: http
  initialDelaySeconds: 5
  periodSeconds: 10
  failureThreshold: 3
```

**Key Metrics to Monitor**:
- Request latency (MCP tool execution time)
- Kubernetes API call latency
- Error rates (4xx, 5xx)
- Authentication failures
- Token validation time
- Memory usage (watch for session storage growth)

**Logging**:
- Structured logging to stderr
- Log levels configurable via environment
- Filters to reduce noise (health checks, verbose FastMCP logs)

#### 4. Security

**Network Security**:
```yaml
# NetworkPolicy example (not included in chart)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: cnpg-mcp-netpol
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: cnpg-mcp
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx
    ports:
    - port: 4204
    - port: 3001
  egress:
  - to:
    - namespaceSelector: {}  # Allow all namespaces (for CNPG API)
    ports:
    - port: 443  # Kubernetes API
  - to:
    - podSelector: {}  # DNS
    ports:
    - port: 53
```

**Pod Security**:
```yaml
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000

securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
    - ALL
```

**RBAC** (See `rbac.yaml`):
- ServiceAccount: `cnpg-mcp-server`
- ClusterRole: `cnpg-cloudnative-pg-edit` (view + edit CNPG resources)
- ClusterRole: `view` (read pods, events, secrets)
- Principle of least privilege

#### 5. Backup and Disaster Recovery

**What to Backup**:
1. **Configuration Files**:
   - `auth0-config.json` (Auth0 credentials)
   - `auth0-values.yaml` (Helm values)
   - `make.env` (Build configuration)

2. **Kubernetes Secrets**:
   ```bash
   kubectl get secret mcp-server-auth0-credentials -o yaml > backup/auth0-secret.yaml
   ```

3. **Auth0 Configuration** (via Management API):
   ```bash
   # Export Auth0 tenant configuration (future script)
   python bin/export-auth0-config.py --output backup/auth0-export.json
   ```

**Disaster Recovery**:
1. Restore configuration files
2. Recreate Kubernetes secret
3. Redeploy with Helm
4. Verify health checks pass

**Recovery Time Objective (RTO)**: ~5 minutes (if backups available)
**Recovery Point Objective (RPO)**: Configuration changes only (no data loss)

---

## Summary

This architecture provides:

✅ **Transport-Agnostic Design**: Same tools work for stdio and HTTP
✅ **Dual Authentication**: FastMCP OAuth (production) + OIDC (testing)
✅ **Sidecar Pattern**: Clean separation of concerns
✅ **Shared Tool Library**: Zero code duplication
✅ **Configuration as Code**: Repeatable, automated setup
✅ **Production Ready**: Security, monitoring, resource limits
✅ **MCP Spec Compliant**: Proper OAuth token issuance
✅ **Kubernetes Native**: Helm charts, health checks, RBAC

**Next Steps**:
- Implement Redis session storage for HA
- Add Prometheus metrics
- Add structured logging with log aggregation
- Implement backup/restore tools
- Add automated testing (unit + integration)

---

## Related Documentation

- [SIDECAR_ARCHITECTURE.md](SIDECAR_ARCHITECTURE.md) - Sidecar pattern decision rationale
- [FASTMCP_OAUTH_MIGRATION.md](FASTMCP_OAUTH_MIGRATION.md) - OAuth proxy migration details
- [OIDC_SETUP.md](OIDC_SETUP.md) - Auth0 setup guide
- [HELM_DEPLOYMENT_GUIDE.md](HELM_DEPLOYMENT_GUIDE.md) - Deployment instructions
- [CLAUDE.md](../CLAUDE.md) - Development guide for Claude Code
- [README.md](../README.md) - Getting started guide
