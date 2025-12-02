# Sidecar Architecture for Dual Authentication Endpoints

## Decision Date
2025-11-28

## Problem Statement

The CNPG MCP server needs to support two different authentication methods:
1. **Production endpoint `/mcp`**: FastMCP OAuth proxy (issues MCP tokens after Auth0 authentication)
2. **Test endpoint `/test`**: Standard OIDC (accepts Auth0 JWT tokens directly)

Both endpoints must:
- Share the same 12 MCP tool implementations
- Have OAuth discovery endpoints (`/register`, `/.well-known/oauth-authorization-server`) accessible at root level for the production endpoint
- Operate independently without authentication bleeding or routing conflicts

## Attempted Solutions

### Attempt 1: Double Decorators (FAILED)
**Approach**: Decorate each tool function with both `@mcp.tool()` and `@mcp2.tool()`

**Result**: `TypeError: First argument to @tool must be a function, got <class 'FunctionTool'>`

**Reason**: Decorators execute bottom-up. The second decorator receives a `FunctionTool` object instead of the original function.

### Attempt 2: Tool Copying via Original Function References (PARTIAL SUCCESS)
**Approach**:
```python
@mcp.tool()
async def my_tool(): ...

# Extract original function and register with mcp2
original_fn = my_tool.fn
mcp2.tool()(original_fn)
```

**Result**: Tool registration worked (12 tools shared), but mounting created new problems.

**Issues**:
- When mounting apps with `Mount("/mcp", app_mcp)`, OAuth endpoints got nested under `/mcp`
- Clients expect OAuth discovery at root: `/.well-known/oauth-authorization-server`, not `/mcp/.well-known/...`
- Attempting to extract and re-mount OAuth routes led to attribute errors and complexity

### Attempt 3: Parent App with Mounts (FAILED)
**Approach**: Create parent Starlette app, mount both FastMCP apps
```python
routes = [
    Mount("/mcp", app_mcp),
    Mount("/test", app_test)
]
app = Starlette(routes=routes)
```

**Result**: OAuth endpoints returned 404

**Reason**: Mounting prefixes all routes, breaking OAuth discovery. Attempts to extract routes via `mcp._get_additional_http_routes()` failed because the method doesn't exist or returns nothing useful.

## Chosen Solution: Kubernetes Sidecar Pattern

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Pod: cnpg-mcp-server                                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────┐  ┌────────────────────┐  │
│  │ Container 1: Main Server     │  │ Container 2: Test  │  │
│  │                              │  │ Sidecar            │  │
│  │ cnpg_mcp_server.py           │  │ cnpg_mcp_test_     │  │
│  │ Port: 3000                   │  │ server.py          │  │
│  │ Auth: FastMCP OAuth          │  │ Port: 3001         │  │
│  │ Endpoint: /mcp               │  │ Auth: OIDC         │  │
│  │ Tools: Import from           │  │ Endpoint: /test    │  │
│  │        cnpg_tools.py         │  │ Tools: Import from │  │
│  │                              │  │        cnpg_tools  │  │
│  └──────────────────────────────┘  └────────────────────┘  │
│           │                                   │             │
└───────────┼───────────────────────────────────┼─────────────┘
            │                                   │
            ▼                                   ▼
     ┌──────────────┐                   ┌─────────────┐
     │ Service:     │                   │ Service:    │
     │ cnpg-mcp     │                   │ cnpg-mcp-   │
     │ -main        │                   │ test        │
     │ Port: 3000   │                   │ Port: 3001  │
     └──────────────┘                   └─────────────┘
            │                                   │
            └───────────┬───────────────────────┘
                        │
                        ▼
                ┌───────────────┐
                │  Ingress      │
                ├───────────────┤
                │ /mcp → :3000  │
                │ /test → :3001 │
                │ /register →   │
                │   :3000       │
                │ /.well-known  │
                │   → :3000     │
                └───────────────┘
```

### Components

#### 1. Shared Tools Library (`src/cnpg_tools.py`)
Contains all 12 MCP tool implementations as standalone async functions:
- `list_postgres_clusters()`
- `get_cluster_status()`
- `create_postgres_cluster()`
- `scale_postgres_cluster()`
- `delete_postgres_cluster()`
- `list_postgres_roles()`
- `create_postgres_role()`
- `update_postgres_role()`
- `delete_postgres_role()`
- `list_postgres_databases()`
- `create_postgres_database()`
- `delete_postgres_database()`

Plus all helper functions and Kubernetes client initialization.

#### 2. Main Server (`src/cnpg_mcp_server.py`)
- Imports tools from `cnpg_tools`
- Creates FastMCP instance with OAuth proxy
- Registers tools with `@mcp.tool()` decorators (wrapping imported functions)
- Runs on port 3000
- OAuth endpoints naturally at root level

#### 3. Test Server (`src/cnpg_mcp_test_server.py`)
- Imports same tools from `cnpg_tools`
- Creates separate FastMCP instance
- Registers tools with `@mcp.tool()` decorators
- Adds OIDC middleware for Auth0 JWT validation
- Runs on port 3001
- No OAuth endpoints (accepts tokens directly)

#### 4. Kubernetes Resources

**Deployment**: Sidecar container
```yaml
spec:
  template:
    spec:
      containers:
      - name: mcp-server
        image: cnpg-mcp:latest
        args: ["--transport", "http", "--port", "3000"]
        ports:
        - containerPort: 3000
          name: mcp

      - name: mcp-test-sidecar  # Optional, controlled by Helm flag
        image: cnpg-mcp:latest
        command: ["python", "src/cnpg_mcp_test_server.py"]
        args: ["--port", "3001"]
        ports:
        - containerPort: 3001
          name: test
```

**Services**:
```yaml
---
apiVersion: v1
kind: Service
metadata:
  name: cnpg-mcp-main
spec:
  selector:
    app: cnpg-mcp-server
  ports:
  - port: 3000
    targetPort: 3000
    name: mcp

---
apiVersion: v1
kind: Service
metadata:
  name: cnpg-mcp-test
spec:
  selector:
    app: cnpg-mcp-server
  ports:
  - port: 3001
    targetPort: 3001
    name: test
```

**Ingress**:
```yaml
spec:
  rules:
  - host: claude-cnpg.wat.im
    http:
      paths:
      - path: /mcp
        pathType: Prefix
        backend:
          service:
            name: cnpg-mcp-main
            port:
              number: 3000

      - path: /test
        pathType: Prefix
        backend:
          service:
            name: cnpg-mcp-test
            port:
              number: 3001

      - path: /register
        pathType: Exact
        backend:
          service:
            name: cnpg-mcp-main
            port:
              number: 3000

      - path: /.well-known/oauth-authorization-server
        pathType: Exact
        backend:
          service:
            name: cnpg-mcp-main
            port:
              number: 3000
```

**Helm Values** (`values.yaml`):
```yaml
testSidecar:
  enabled: true  # Set to false to disable test endpoint
  image:
    tag: latest  # Can use same or different tag
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 200m
      memory: 256Mi
```

## Benefits

1. **Complete Separation**: Each server runs independently with its own auth, no bleeding or conflicts
2. **OAuth Standards Compliance**: OAuth discovery endpoints naturally at root on main server
3. **Standard Kubernetes Patterns**: Sidecar is well-understood, documented pattern
4. **Feature Flag**: Easy to enable/disable test endpoint via Helm
5. **Port-Forward Friendly**: Can target either container independently
6. **No Routing Complexity**: Each server has full FastMCP app, no mounting hacks
7. **Shared Code**: Tools maintained in one place, imported by both
8. **Independent Scaling**: Could scale containers independently if needed (though typically not necessary)
9. **Clear Separation of Concerns**: Production vs test responsibilities are obvious

## Trade-offs

- **Resource Usage**: Two containers instead of one (mitigated: test sidecar is optional)
- **Slightly More Complex Deployment**: Sidecar pattern vs single container
- **Code Duplication**: Two server files with similar structure (mitigated: shared tools library)

## Implementation Checklist

- [ ] Create `src/cnpg_tools.py` with all 12 tools and helpers
- [ ] Update `src/cnpg_mcp_server.py` to import from shared library
- [ ] Create `src/cnpg_mcp_test_server.py` with OIDC auth
- [ ] Update `kubernetes-deployment.yaml` for sidecar
- [ ] Create `kubernetes-deployment-test-sidecar.yaml` manifest
- [ ] Update Helm chart with `testSidecar.enabled` flag
- [ ] Update Ingress to route both paths
- [ ] Create separate Service for test endpoint
- [ ] Update documentation (`CLAUDE.md`, `README.md`)
- [ ] Test both endpoints independently
- [ ] Test Ingress routing

## Testing Strategy

### Local Testing
```bash
# Terminal 1: Main server
export OIDC_ISSUER=... AUTH0_CLIENT_ID=... AUTH0_CLIENT_SECRET=...
python src/cnpg_mcp_server.py --transport http --port 3000

# Terminal 2: Test server
export OIDC_ISSUER=... OIDC_AUDIENCE=...
python src/cnpg_mcp_test_server.py --port 3001

# Terminal 3: Test both
# Main (OAuth)
./test/test-mcp.py --transport http --url http://localhost:3000

# Test (OIDC)
./test/get-user-token.py  # Get Auth0 JWT
./test/test-mcp.py --transport http --url http://localhost:3001/test --token-file /tmp/user-token.txt
```

### Kubernetes Testing
```bash
# Port-forward main
kubectl port-forward pod/cnpg-mcp-server-xxx 3000:3000

# Port-forward test (separate terminal)
kubectl port-forward pod/cnpg-mcp-server-xxx 3001:3001

# Test via Ingress
curl https://claude-cnpg.wat.im/.well-known/oauth-authorization-server
curl -H "Authorization: Bearer <token>" https://claude-cnpg.wat.im/test/
```

## References

- FastMCP Documentation: https://github.com/jlowin/fastmcp
- Kubernetes Sidecar Pattern: https://kubernetes.io/docs/concepts/workloads/pods/
- OAuth 2.0 Discovery: RFC 8414

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2025-11-28 | Initial sidecar architecture decision | Claude Code |
