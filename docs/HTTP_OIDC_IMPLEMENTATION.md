# HTTP Mode with OIDC Authentication - Implementation Summary

This document summarizes the implementation of HTTP transport mode with OIDC/OAuth2 authentication for the CloudNativePG MCP Server.

## What Was Implemented

### 1. OIDC Authentication Module (`auth_oidc.py`)

A complete OIDC/OAuth2 authentication provider with the following features:

#### **OIDCAuthProvider Class**
- JWT bearer token verification using RS256/ES256 signatures
- Automatic JWKS (JSON Web Key Set) discovery from OIDC provider
- JWKS caching with TTL to minimize network requests
- Standard JWT claims validation:
  - Issuer (`iss`) verification
  - Audience (`aud`) verification
  - Expiration (`exp`) checking
  - Signature verification using JWKS
  - Optional scope validation

#### **JWKSCache Class**
- Caches JWKS responses to avoid repeated fetches
- Configurable TTL (default: 1 hour)
- Automatic refresh when cache expires
- Async implementation using `httpx`

#### **OIDCAuthMiddleware Class**
- Starlette middleware for request authentication
- Intercepts all HTTP requests (except excluded paths)
- Extracts and validates JWT from `Authorization: Bearer <token>` header
- Injects authenticated user claims into request state
- Returns proper HTTP 401 responses for auth failures
- Excludes health check and metadata endpoints from authentication

#### **DCR Proxy Support**
- Environment variable configuration for DCR proxy URL
- Advertises DCR endpoint in OAuth metadata
- Enables dynamic client registration for non-DCR-capable IdPs

#### **OAuth Metadata Endpoint**
- RFC 8414 compliant authorization server metadata
- Exposed at `/.well-known/oauth-authorization-server`
- Provides:
  - Issuer information
  - JWKS URI
  - Supported scopes and grant types
  - DCR registration endpoint (if configured)

### 2. Enhanced HTTP Transport (`cnpg_mcp_server.py`)

Updated the `run_http_transport()` function to:

- Initialize OIDC authentication when `OIDC_ISSUER` is set
- Create authentication middleware stack
- Add metadata routes from auth provider
- Add unauthenticated health check endpoint at `/health`
- Use Uvicorn as ASGI server with proper configuration
- Provide clear startup messages about authentication status
- Fail fast if OIDC configuration is invalid

**Environment Variables:**
- `OIDC_ISSUER` (required): OIDC provider URL
- `OIDC_AUDIENCE` (required): Expected JWT audience claim
- `OIDC_JWKS_URI` (optional): Override JWKS URI
- `DCR_PROXY_URL` (optional): DCR proxy URL
- `OIDC_SCOPE` (optional): Required scope (default: "openid")

### 3. Production-Ready Dockerfile

Created `Dockerfile` with:
- Python 3.11-slim base image
- Multi-stage optimization for layer caching
- Non-root user for security (uid 1000)
- Health check using `/health` endpoint
- Proper working directory and file ownership
- Exposed port 3000
- Automatic in-cluster Kubernetes config detection
- Default CMD for HTTP transport mode

**Security Features:**
- Runs as non-root user `mcpuser`
- Minimal system dependencies
- No unnecessary packages
- Clean apt cache to reduce image size

### 4. Convenience Start Script (`start-http.sh`)

Bash script that:
- Validates OIDC configuration before startup
- Provides clear warnings if running in insecure mode
- Displays current configuration (OIDC, Kubernetes)
- Offers interactive confirmation for insecure mode
- Uses environment variables for host/port defaults
- Color-coded output for better UX
- Properly exec's the Python server for signal handling

### 5. Test Inspector Tool (`test-inspector.sh`)

Shell script wrapper for the MCP Inspector with:

#### **Transport Modes:**
- `stdio` - Test server via stdio transport (default)
- `http` - Test server via HTTP/SSE transport

#### **Features:**
- Uses `npx @modelcontextprotocol/inspector` for testing
- JWT token authentication support for HTTP mode
- Token from file or command-line argument
- Support for both authenticated and unauthenticated HTTP
- Automatic /mcp endpoint appending
- Color-coded output
- Clear error messages

#### **Usage Examples:**
```bash
# Test stdio mode (local development)
./test-inspector.sh --transport stdio

# Test HTTP mode with authentication
./test-inspector.sh --transport http \
  --url http://localhost:3000 \
  --token-file token.txt

# Test HTTP mode with inline token
./test-inspector.sh --transport http \
  --url http://localhost:3000 \
  --token "$TOKEN"

# Test production endpoint
./test-inspector.sh --transport http \
  --url https://mcp-api.example.com \
  --token-file token.txt
```

### 6. Updated Dependencies (`requirements.txt`)

Added production dependencies:
- `uvicorn[standard]>=0.27.0` - ASGI server with all features
- `starlette>=0.35.0` - ASGI framework for middleware
- `httpx>=0.25.0` - Async HTTP client for JWKS fetching
- `authlib>=1.3.0` - OAuth2/OIDC and JWT support
- `cryptography>=41.0.0` - Crypto primitives for JWT

### 7. Comprehensive Documentation

#### **OIDC_SETUP.md**
Complete setup guide (500+ lines) covering:
- Architecture diagram
- Environment variable configuration
- IdP-specific setup instructions (Auth0, Keycloak, Okta, Azure AD, Google)
- Kubernetes deployment with ConfigMaps and Secrets
- Ingress configuration with TLS
- Testing procedures
- DCR proxy setup guide
- Security best practices
- Troubleshooting guide with solutions
- Example configurations for major IdPs

#### **Updated CLAUDE.md**
Enhanced project documentation with:
- OIDC authentication overview in key characteristics
- HTTP mode startup instructions
- OIDC environment variables
- Quick start guide
- File reference for OIDC components
- Security considerations for HTTP mode
- Updated transport modes documentation

### 8. Kubernetes Deployment Manifest (`kubernetes-deployment-oidc.yaml`)

Production-ready Kubernetes resources:

#### **ConfigMap** (`cnpg-mcp-oidc-config`)
- OIDC configuration with detailed comments
- Examples for all major IdPs
- Optional settings documented

#### **Deployment**
- 2 replicas for high availability
- Resource requests and limits
- Non-root security context (uid 1000, fsGroup 1000)
- Security: no privilege escalation, drop all capabilities
- Health checks (liveness and readiness)
- Environment from ConfigMap
- Proper labels for service discovery

#### **Service**
- ClusterIP type for internal access
- Port 3000 exposed
- Selector matches deployment

#### **Ingress**
- TLS with cert-manager integration
- Security headers (X-Frame-Options, X-Content-Type-Options, etc.)
- Request size limits
- Timeout configuration for long operations
- Multiple hosts support

#### **HorizontalPodAutoscaler**
- CPU-based scaling (70% threshold)
- Memory-based scaling (80% threshold)
- 2-10 replica range
- Stabilization windows for smooth scaling
- Multiple scaling policies

#### **PodDisruptionBudget**
- Ensures minimum 1 replica during cluster operations
- Protects against total service unavailability

#### **NetworkPolicy** (Optional)
- Ingress: Allow only from ingress controller
- Egress: Allow DNS, Kubernetes API, OIDC provider
- Namespace-based selectors

## Architecture

```
┌──────────────┐
│    Client    │
│  (with JWT)  │
└──────┬───────┘
       │ HTTPS (via Ingress)
       ↓
┌─────────────────────────────────────────────┐
│           Kubernetes Ingress                │
│        (TLS Termination)                    │
└──────────────┬──────────────────────────────┘
               │ HTTP
               ↓
┌─────────────────────────────────────────────┐
│      Service (cnpg-mcp-server)              │
│           ClusterIP: 3000                   │
└──────────────┬──────────────────────────────┘
               │
       ┌───────┴───────┐
       │               │
       ↓               ↓
┌─────────────┐ ┌─────────────┐
│  Pod 1      │ │  Pod 2      │
│  (Replica)  │ │  (Replica)  │
└─────────────┘ └─────────────┘
       │               │
       └───────┬───────┘
               │
               ↓
    ┌──────────────────────┐
    │  OIDCAuthMiddleware  │
    │  (auth_oidc.py)      │
    └──────────┬───────────┘
               │ Validates JWT
               │ Fetches JWKS
               ↓
         ┌───────────┐
         │ OIDC IdP  │
         │  (JWKS)   │
         └───────────┘
               │
               ↓
    ┌──────────────────────┐
    │  FastMCP Server      │
    │  (cnpg_mcp_server)   │
    └──────────┬───────────┘
               │
               ↓
    ┌──────────────────────┐
    │  Kubernetes API      │
    │  (via ServiceAccount)│
    └──────────┬───────────┘
               │
               ↓
    ┌──────────────────────┐
    │  CloudNativePG       │
    │  Operator            │
    └──────────────────────┘
```

## Security Features

### Authentication
- ✅ JWT bearer token authentication (OAuth2/OIDC)
- ✅ RS256/ES256 signature verification
- ✅ JWKS-based public key discovery
- ✅ Automatic key rotation support
- ✅ Issuer validation
- ✅ Audience validation
- ✅ Expiration checking
- ✅ Optional scope validation

### Authorization
- ✅ Kubernetes RBAC via ServiceAccount
- ✅ CloudNativePG role bindings
- ✅ Namespace isolation support
- ✅ Network policies

### Transport Security
- ✅ TLS termination at Ingress
- ✅ HTTPS-only with redirect
- ✅ Security headers (HSTS, X-Frame-Options, CSP-ready)

### Container Security
- ✅ Non-root user (uid 1000)
- ✅ Read-only root filesystem capable
- ✅ No privilege escalation
- ✅ All capabilities dropped
- ✅ Security context enforced

### Best Practices
- ✅ Health checks for liveness and readiness
- ✅ Resource limits and requests
- ✅ Horizontal pod autoscaling
- ✅ Pod disruption budgets
- ✅ Structured logging
- ✅ Graceful shutdown

## Testing

### Local Development

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set OIDC config (or run insecure for testing)
export OIDC_ISSUER=https://your-idp.example.com
export OIDC_AUDIENCE=mcp-api

# 3. Start server
./start-http.sh

# 4. Test health (no auth)
curl http://localhost:3000/health

# 5. Get JWT token from your IdP
# (varies by IdP - see OIDC_SETUP.md)

# 6. Test with inspector
./test-inspector.sh --transport http \
  --url http://localhost:3000 \
  --token "$TOKEN"
```

### Kubernetes Deployment

```bash
# 1. Build and push image
docker build -t your-registry/cnpg-mcp-server:latest .
docker push your-registry/cnpg-mcp-server:latest

# 2. Update ConfigMap with your OIDC settings
kubectl edit configmap cnpg-mcp-oidc-config

# 3. Deploy
kubectl apply -f kubernetes-deployment-oidc.yaml

# 4. Check pods
kubectl get pods -l app=cnpg-mcp-server

# 5. Check logs
kubectl logs -f deployment/cnpg-mcp-server

# 6. Test via Ingress
curl https://mcp-api.example.com/health
```

## Files Created/Modified

### New Files
1. `auth_oidc.py` - OIDC authentication provider (447 lines)
2. `OIDC_SETUP.md` - Complete setup documentation (500+ lines)
3. `start-http.sh` - Convenience startup script (75 lines)
4. `test-inspector.sh` - MCP Inspector wrapper for stdio and HTTP testing (150+ lines)
5. `kubernetes-deployment-oidc.yaml` - Production K8s manifest (300+ lines)
6. `HTTP_OIDC_IMPLEMENTATION.md` - This summary document

### Modified Files
1. `cnpg_mcp_server.py` - Updated `run_http_transport()` function
2. `requirements.txt` - Added HTTP and OIDC dependencies
3. `Dockerfile` - Enhanced for production with health checks
4. `CLAUDE.md` - Added OIDC documentation sections

## Configuration Examples

### Auth0
```bash
export OIDC_ISSUER=https://your-tenant.auth0.com
export OIDC_AUDIENCE=https://api.example.com/mcp
```

### Keycloak
```bash
export OIDC_ISSUER=https://keycloak.example.com/realms/myrealm
export OIDC_AUDIENCE=mcp-api
```

### Azure AD
```bash
export OIDC_ISSUER=https://login.microsoftonline.com/tenant-id/v2.0
export OIDC_AUDIENCE=api://mcp-api
```

### Google
```bash
export OIDC_ISSUER=https://accounts.google.com
export OIDC_AUDIENCE=your-client-id.apps.googleusercontent.com
```

## Next Steps

### For Development
1. Configure your OIDC provider (see `OIDC_SETUP.md`)
2. Set environment variables
3. Run `./start-http.sh`
4. Test with `test-inspector.py`

### For Production
1. Build Docker image
2. Push to container registry
3. Update `kubernetes-deployment-oidc.yaml` with your settings
4. Deploy to Kubernetes
5. Configure Ingress with TLS
6. Set up monitoring and logging

### For DCR Proxy (if needed)
1. Deploy DCR proxy service
2. Set `DCR_PROXY_URL` environment variable
3. Configure proxy to translate to your IdP's API

## Standards Compliance

This implementation complies with:
- ✅ RFC 6749 - OAuth 2.0 Authorization Framework
- ✅ RFC 7519 - JSON Web Token (JWT)
- ✅ RFC 8414 - OAuth 2.0 Authorization Server Metadata
- ✅ OpenID Connect Core 1.0
- ✅ RFC 7591 - OAuth 2.0 Dynamic Client Registration (DCR proxy support)

## Performance Considerations

- **JWKS Caching**: 1-hour TTL reduces IdP requests
- **Connection Pooling**: httpx async client reuses connections
- **Async Operations**: Non-blocking I/O throughout
- **Health Checks**: Unauthenticated for fast monitoring
- **HPA**: Auto-scales based on load (2-10 replicas)
- **Resource Limits**: Prevents resource exhaustion

## Limitations and Future Enhancements

### Current Limitations
- Only supports Bearer token authentication (not mTLS)
- JWKS cache is in-memory (not distributed)
- No token revocation check (relies on expiration)
- No rate limiting built-in (use Ingress controller)

### Potential Enhancements
- Add Redis-based JWKS cache for multi-replica consistency
- Support token introspection (RFC 7662)
- Add rate limiting middleware
- Support mTLS client authentication
- Add audit logging middleware
- Metrics/OpenTelemetry instrumentation
- Admin API endpoints

## Support and Troubleshooting

See `OIDC_SETUP.md` for:
- Common error messages and solutions
- IdP-specific configuration help
- Debugging techniques
- Security best practices

## License and Attribution

This implementation uses:
- FastMCP - MCP server framework
- Authlib - OAuth2/OIDC library
- Starlette - ASGI framework
- Uvicorn - ASGI server
- httpx - Async HTTP client

All dependencies are included in `requirements.txt` with compatible licenses.
