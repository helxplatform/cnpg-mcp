# Migration to FastMCP OAuth Proxy

## Summary

This document describes the migration from a custom OIDC authentication implementation to FastMCP's built-in OAuth Proxy. This migration solves the JWE token problem where Claude.ai was receiving encrypted Auth0 tokens instead of signed JWT tokens from the MCP server.

## Problem Statement

### The JWE Token Issue

The original implementation had a fundamental architectural problem:

1. **Custom OIDCAuthProvider** (`auth_oidc.py`):
   - Validated JWT tokens from Auth0
   - Had DCR proxy functionality
   - Attempted to decrypt JWE tokens
   - **Problem**: Passed Auth0 tokens directly to Claude.ai

2. **Why This Failed**:
   - Auth0 encrypts tokens (JWE format) for confidential clients
   - MCP server was acting as a "resource server" only
   - According to MCP specification, the MCP server **MUST** act as its own OAuth authorization server
   - The MCP server should issue its own tokens, not pass through Auth0 tokens

### Root Cause Analysis

From diagnostic files (`diag/p0.txt` and `diag/p1.txt`):

> **The MCP specification is definitive: The MCP server must act as its own authorization server and generate the final access token that the MCP client (Claude) uses for resource requests.**

The correct flow should be:
1. Client initiates OAuth flow with MCP server
2. MCP server redirects to Auth0 for authentication
3. Auth0 redirects back with authorization code
4. **MCP server exchanges code for Auth0 token (internal)**
5. **MCP server issues its own JWT token to client**
6. Client uses MCP token for subsequent requests

## Solution: FastMCP OAuth Proxy

### What is FastMCP OAuth Proxy?

FastMCP (v2.12+) includes a built-in OAuth Proxy that implements the correct token issuance pattern:

- **Upstream Integration**: Connects to Auth0 (or other OAuth providers)
- **Token Exchange**: Exchanges authorization codes for Auth0 tokens internally
- **Session Management**: Stores Auth0 tokens securely (encrypted with Fernet)
- **Token Issuance**: Issues MCP-signed JWT tokens to clients (signed with HS256)
- **Token Validation**: Validates client tokens and looks up stored Auth0 sessions

### Key Benefits

1. **Solves JWE Problem**: Clients receive signed JWT tokens, not encrypted JWE tokens
2. **Production-Ready**: Battle-tested implementation with security features
3. **Zero Configuration**: Pre-configured for Auth0, GitHub, Google, Azure, AWS, etc.
4. **DCR Support**: Built-in Dynamic Client Registration proxy
5. **Consent Screens**: User consent UI with CSRF protection
6. **PKCE Security**: End-to-end PKCE validation (client → proxy → Auth0)

## Implementation Changes

### 1. New Auth Module: `auth_fastmcp.py`

**File**: `/workspaces/cnpg-mcp/src/auth_fastmcp.py`

```python
from fastmcp.server.auth import OAuthProxy
from fastmcp.server.auth.providers.jwt import JWTVerifier

def create_auth0_oauth_proxy(config_path: Optional[str] = None) -> OAuthProxy:
    """Create FastMCP OAuth Proxy configured for Auth0."""

    # Create JWT verifier for Auth0 tokens (used internally by proxy)
    token_verifier = JWTVerifier(
        jwks_uri=jwks_uri,
        issuer=issuer,
        audience=audience
    )

    # Create OAuth Proxy (handles token issuance)
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

**Key Components**:
- `OAuthProxy`: Main proxy class that handles OAuth flow
- `JWTVerifier`: Validates Auth0 tokens (internal use only)
- `upstream_*`: Configuration for Auth0 endpoints and credentials
- `extra_*_params`: Auth0-specific parameters (audience requirement)
- `forward_pkce`: Enable PKCE forwarding to Auth0
- `require_authorization_consent`: Show user consent screen

### 2. Updated HTTP Transport: `cnpg_mcp_server.py`

**Changes**:

```python
# OLD: Custom OIDC provider with middleware
from auth_oidc import OIDCAuthProvider, OIDCAuthMiddleware
auth_provider = OIDCAuthProvider()
middleware.append(Middleware(OIDCAuthMiddleware, auth_provider=auth_provider))
app = mcp.http_app(transport="http", path="/mcp")
app.add_middleware(...)

# NEW: FastMCP OAuth Proxy (built-in)
from auth_fastmcp import create_auth0_oauth_proxy
auth_proxy = create_auth0_oauth_proxy()
authenticated_mcp = FastMCP("cloudnative-pg", auth=auth_proxy)
# Register all tools from main mcp instance
for tool_name, tool_func in mcp._tools.items():
    authenticated_mcp._tools[tool_name] = tool_func
# Run with built-in auth
await authenticated_mcp.run(transport="http", host=host, port=port)
```

**Key Changes**:
- FastMCP handles OAuth endpoints automatically (`/authorize`, `/token`, `/register`)
- OAuth metadata exposed at `/.well-known/oauth-authorization-server`
- Token verification middleware included
- No manual Starlette middleware configuration needed

### 3. Updated ConfigMap: `chart/templates/configmap.yaml`

**Changes**:

```yaml
# OLD: Custom OIDC config
issuer: "https://domain.auth0.com"
audience: "https://api.example.com/mcp"
mgmt_client_id: "..."  # Management API client
mgmt_client_secret_file: "/etc/mcp/secrets/client-secret"
client_secrets_file: "/etc/mcp/secrets/client-secrets.yaml"
dcr_proxy_url: "..."

# NEW: FastMCP OAuth Proxy config
issuer: "https://domain.auth0.com"
audience: "https://api.example.com/mcp"
client_id: "..."  # Pre-registered Auth0 application
client_secret_file: "/etc/mcp/secrets/client-secret"
public_url: "https://mcp.example.com"
```

**Key Changes**:
- Added `client_id`: Pre-registered Auth0 application (confidential client)
- Added `client_secret_file`: Path to client secret (mounted from K8s Secret)
- Removed `mgmt_client_id`: No longer need Management API to convert clients
- Removed `client_secrets_file`: No longer need to decrypt JWE tokens manually
- Removed `dcr_proxy_url`: FastMCP OAuth Proxy IS the DCR proxy
- Added `public_url`: Required for OAuth callback URL construction

### 4. Updated Setup Script: `bin/setup-auth0.py`

**Changes**:

1. **Helm Values**:
```yaml
# OLD
oidc:
  issuer: "..."
  audience: "..."
  mgmt_client_id: "..."  # Management API client

# NEW
oidc:
  issuer: "..."
  audience: "..."
  clientId: "..."  # Pre-registered application (test_client)
  clientSecretsSecret: "mcp-oidc-secret"
```

2. **New Script Generation**: `create-k8s-secret.sh`
```bash
#!/bin/bash
kubectl create secret generic mcp-oidc-secret \
  -n default \
  --from-literal=client-secret="<TEST_CLIENT_SECRET>"
```

3. **Updated Next Steps**:
```
1. Create Kubernetes Secret: ./create-k8s-secret.sh
2. Build and push container image: make build push
3. Deploy with Helm: helm install mcp-server ./chart -f auth0-values.yaml
4. Verify deployment: kubectl logs -l app.kubernetes.io/name=cnpg-mcp -f
5. Test OAuth flow: curl https://domain/.well-known/oauth-authorization-server
```

## Configuration Requirements

### Required Configuration

1. **Auth0 Application** (pre-registered, confidential client):
   - Client ID
   - Client Secret
   - Application Type: Regular Web Application or Native
   - Token Endpoint Authentication: Client Secret (Post or Basic)
   - Allowed Callback URLs: `https://your-mcp-server.com/auth/callback`
   - Allowed Logout URLs: `https://your-mcp-server.com`

2. **Auth0 API** (API identifier):
   - Identifier (audience): `https://your-api.example.com/mcp`
   - Signing Algorithm: RS256

3. **Kubernetes Secret**:
   - Name: `mcp-oidc-secret`
   - Key: `client-secret`
   - Value: Auth0 application client secret

### Configuration File (`/etc/mcp/oidc.yaml`)

```yaml
# Auth0 Configuration
issuer: "https://your-domain.auth0.com"
audience: "https://your-api.example.com/mcp"
client_id: "abc123..."
client_secret_file: "/etc/mcp/secrets/client-secret"

# Server Configuration
public_url: "https://mcp.example.com"

# Optional
jwks_uri: "https://your-domain.auth0.com/.well-known/jwks.json"
scope: "openid"
```

## Token Flow

### New Flow (FastMCP OAuth Proxy)

```
┌─────────┐         ┌──────────────┐         ┌─────────┐
│ Claude  │         │ MCP Server   │         │ Auth0   │
└─────────┘         │ (OAuth Proxy)│         └─────────┘
     │              └──────────────┘              │
     │                     │                      │
     │ 1. Initiate OAuth   │                      │
     │────────────────────>│                      │
     │                     │                      │
     │ 2. Redirect to Auth0│                      │
     │<────────────────────│                      │
     │                     │                      │
     │ 3. Authenticate                            │
     │───────────────────────────────────────────>│
     │                     │                      │
     │ 4. Auth Code        │                      │
     │<────────────────────│<─────────────────────│
     │                     │                      │
     │                     │ 5. Exchange for token│
     │                     │─────────────────────>│
     │                     │                      │
     │                     │ 6. Auth0 Token (JWE) │
     │                     │<─────────────────────│
     │                     │                      │
     │                     │ 7. Store + Generate  │
     │                     │    MCP Token (JWT)   │
     │                     │                      │
     │ 8. MCP Token (JWT)  │                      │
     │<────────────────────│                      │
     │                     │                      │
     │ 9. API Request      │                      │
     │    + MCP Token      │                      │
     │────────────────────>│                      │
     │                     │                      │
     │                     │ 10. Validate MCP Token│
     │                     │     Lookup Auth0 Token│
     │                     │                      │
     │ 11. API Response    │                      │
     │<────────────────────│                      │
```

### Key Points

1. **Auth0 Token (Step 6)**: May be JWE encrypted - stored internally by proxy
2. **MCP Token (Step 7)**: Signed JWT (HS256) - issued to client
3. **Token Storage**: Auth0 tokens encrypted with Fernet, indexed by MCP token JTI
4. **Token Validation**: MCP server validates its own tokens, not Auth0 tokens
5. **Session Binding**: MCP token maps to Auth0 session (for refresh, revocation)

## Testing

### 1. Test OAuth Metadata

```bash
curl https://your-mcp-server.com/.well-known/oauth-authorization-server | jq
```

Expected response:
```json
{
  "issuer": "https://your-mcp-server.com",
  "authorization_endpoint": "https://your-mcp-server.com/authorize",
  "token_endpoint": "https://your-mcp-server.com/token",
  "registration_endpoint": "https://your-mcp-server.com/register",
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "response_types_supported": ["code"],
  "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
  "code_challenge_methods_supported": ["S256"]
}
```

### 2. Test Dynamic Client Registration

```bash
curl -X POST https://your-mcp-server.com/register \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "Test Client",
    "redirect_uris": ["http://localhost:8080/callback"]
  }' | jq
```

Expected response (client credentials):
```json
{
  "client_id": "...",
  "client_name": "Test Client",
  "redirect_uris": ["http://localhost:8080/callback"],
  "token_endpoint_auth_method": "none"
}
```

### 3. Verify Token Format

After completing OAuth flow, inspect the access token:

```bash
# Token should be 3 parts (JWT), not 5 parts (JWE)
echo $ACCESS_TOKEN | awk -F. '{print NF}'
# Expected: 3

# Decode header
echo $ACCESS_TOKEN | cut -d. -f1 | base64 -d | jq
# Expected: {"alg":"HS256","typ":"JWT"}
# NOT: {"alg":"dir","enc":"A256GCM","iss":"https://domain.auth0.com/"}
```

### 4. Check Server Logs

```bash
kubectl logs -l app.kubernetes.io/name=cnpg-mcp -f
```

Expected log messages:
```
INFO: Initializing FastMCP OAuth Proxy for Auth0...
INFO: ✅ OAuth Proxy configured:
INFO:    Provider: Auth0
INFO:    Authorization: https://domain.auth0.com/authorize
INFO:    Token Exchange: https://domain.auth0.com/oauth/token
INFO:    Public URL: https://mcp.example.com
INFO:    PKCE Enabled: True
INFO:    User Consent: True
INFO: 🚀 FastMCP OAuth Proxy Authentication Enabled
INFO: Token Flow:
INFO:   1. Client initiates OAuth flow with MCP server
INFO:   2. MCP server redirects to Auth0 for authentication
INFO:   3. Auth0 redirects back with authorization code
INFO:   4. MCP server exchanges code for Auth0 token (internal)
INFO:   5. MCP server issues its own JWT token to client
INFO:   6. Client uses MCP token for subsequent requests
```

## Rollback Plan

If issues arise, you can rollback to the custom OIDC implementation:

1. **Revert Code Changes**:
```bash
git revert <commit-hash>
```

2. **Update ConfigMap**:
```yaml
oidc:
  issuer: "..."
  audience: "..."
  mgmt_client_id: "..."
  mgmt_client_secret_file: "/etc/mcp/secrets/client-secret"
```

3. **Redeploy**:
```bash
helm upgrade mcp-server ./chart -f auth0-values-old.yaml
```

## Benefits

1. **Solves JWE Token Problem**: ✅ Clients receive JWT, not JWE
2. **Production-Ready**: ✅ Battle-tested FastMCP implementation
3. **Less Code to Maintain**: ✅ Removed ~1200 lines of custom auth code
4. **Better Security**: ✅ Encrypted token storage, consent screens, CSRF protection
5. **Standards Compliant**: ✅ Full RFC 6749 OAuth 2.0 implementation
6. **Better Logging**: ✅ Clear token flow messages for debugging

## References

- **FastMCP OAuth Proxy Documentation**: https://gofastmcp.com/servers/auth/oauth-proxy
- **FastMCP GitHub**: https://github.com/jlowin/fastmcp
- **MCP Specification**: https://modelcontextprotocol.io/
- **RFC 6749 (OAuth 2.0)**: https://datatracker.ietf.org/doc/html/rfc6749
- **Diagnostic Files**:
  - `/workspaces/cnpg-mcp/diag/p0.txt` - Root cause analysis
  - `/workspaces/cnpg-mcp/diag/p1.txt` - FastMCP solution explanation
