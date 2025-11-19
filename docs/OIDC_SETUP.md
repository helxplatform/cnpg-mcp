# OIDC Authentication Setup Guide

This guide explains how to configure OIDC/OAuth2 authentication for the CloudNativePG MCP Server when running in HTTP transport mode.

## Quick Start (Simple Case)

**If your MCP server is already deployed at a known URL with OIDC+DCR enabled:**

### For Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "cnpg": {
      "url": "https://mcp-api.example.com/mcp"
    }
  }
}
```

That's it! Claude Desktop will auto-discover OAuth configuration and handle authentication.

### For Testing with MCP Inspector

```bash
./test-inspector.sh --transport http --url https://mcp-api.example.com
```

The inspector handles authentication automatically.

### For Other MCP Clients

Just provide the server URL - the MCP SDK handles the rest:

```python
from mcp import ClientSession, HttpServerParameters

async with ClientSession(
    HttpServerParameters(url="https://mcp-api.example.com/mcp")
) as session:
    await session.initialize()
    # Use session...
```

---

**The rest of this guide is for server administrators who need to configure OIDC authentication, or for advanced use cases like manual token management.**

---

## Overview

The CloudNativePG MCP Server supports OIDC authentication for secure remote access. Key features:

- **JWT Bearer Token Verification**: Uses RS256/ES256 signatures
- **JWKS-based Public Key Discovery**: Automatic key rotation support
- **Dynamic Client Registration (DCR)**: Auto-registration for MCP clients via RFC 7591
- **DCR Proxy Support**: Works with IdPs that don't support DCR natively
- **Standards Compliant**: Implements RFC 8414 (OAuth 2.0 Authorization Server Metadata)

## Architecture

```
┌─────────────┐         ┌──────────────┐         ┌──────────────────┐
│   Client    │  JWT    │  MCP Server  │  JWKS   │   OIDC IdP       │
│             ├────────→│  (HTTP Mode) ├────────→│  (Auth Provider) │
│             │         │              │         │                  │
└─────────────┘         └──────────────┘         └──────────────────┘
                               │
                               │ (optional)
                               ↓
                        ┌──────────────┐
                        │  DCR Proxy   │
                        │  (for IdPs   │
                        │  without DCR)│
                        └──────────────┘
```

## Configuration

### Required Environment Variables

#### `OIDC_ISSUER` (Required)
The OIDC issuer URL. This is the base URL of your identity provider.

```bash
export OIDC_ISSUER=https://auth.example.com
```

**Examples:**
- Auth0: `https://your-tenant.auth0.com`
- Keycloak: `https://keycloak.example.com/realms/your-realm`
- Okta: `https://your-org.okta.com`
- Azure AD: `https://login.microsoftonline.com/{tenant-id}/v2.0`
- Google: `https://accounts.google.com`

#### `OIDC_AUDIENCE` (Required)
The expected audience (`aud`) claim in JWT tokens. This should be set to a unique identifier for your MCP API.

```bash
export OIDC_AUDIENCE=mcp-api
# or use a URI format
export OIDC_AUDIENCE=https://api.example.com/mcp
```

**Important:** Make sure your IdP is configured to issue tokens with this audience value.

### Optional Environment Variables

#### `OIDC_JWKS_URI` (Optional)
Override the JWKS URI. By default, the server auto-discovers this from the issuer's `.well-known/openid-configuration` endpoint.

```bash
export OIDC_JWKS_URI=https://auth.example.com/.well-known/jwks.json
```

Only set this if:
- Your IdP doesn't support OIDC discovery
- You need to use a specific JWKS endpoint
- You're using a custom key server

#### `DCR_PROXY_URL` (Optional)
URL of a Dynamic Client Registration proxy for IdPs that don't support DCR natively.

```bash
export DCR_PROXY_URL=https://dcr-proxy.example.com/register
```

The DCR proxy allows clients to dynamically register themselves even when the upstream IdP doesn't support RFC 7591 (OAuth 2.0 Dynamic Client Registration).

#### `OIDC_SCOPE` (Optional)
Required scope for access. Default is `openid`.

```bash
export OIDC_SCOPE=openid
# or require additional scopes
export OIDC_SCOPE="openid profile email"
```

## IdP Configuration

### 1. Register the MCP Server

In your OIDC provider, register a new application/client for the MCP server.

**Client Type:** Confidential Client / Web Application / API
**Redirect URIs:** Not required for API server (only for clients)
**Grant Types:** `authorization_code`, `client_credentials`
**Token Endpoint Auth Method:** `client_secret_post` or `client_secret_basic`

### 2. Configure Audience

Ensure your IdP includes the correct audience (`aud`) claim in access tokens.

**Auth0:**
```
API Identifier: mcp-api
```

**Keycloak:**
```
Client > Settings > Valid Redirect URIs: (not needed for API)
Client > Mappers > Create Audience Mapper
  - Token Claim Name: aud
  - Included Client Audience: mcp-api
```

**Azure AD:**
```
App Registration > Expose an API
  - Application ID URI: api://mcp-api
```

### 3. Configure Scopes

Create an `openid` scope (or use the default) and any additional scopes your application requires.

### 4. Obtain Client Credentials (For Clients)

Your MCP clients will need to obtain access tokens from the IdP. This typically involves:

1. **Authorization Code Flow** (for user-interactive clients):
   - Client redirects user to IdP authorization endpoint
   - User authenticates and consents
   - IdP redirects back with authorization code
   - Client exchanges code for access token

2. **Client Credentials Flow** (for machine-to-machine):
   - Client authenticates with IdP using client ID and secret
   - Receives access token directly

## Kubernetes Deployment

### Using Environment Variables

Create a ConfigMap and Secret:

```yaml
# config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cnpg-mcp-oidc-config
  namespace: default
data:
  OIDC_ISSUER: "https://auth.example.com"
  OIDC_AUDIENCE: "mcp-api"
  # Optional:
  # OIDC_JWKS_URI: "https://auth.example.com/.well-known/jwks.json"
  # DCR_PROXY_URL: "https://dcr-proxy.example.com/register"
  # OIDC_SCOPE: "openid"
```

### Deployment with OIDC

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cnpg-mcp-server
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: cnpg-mcp-server
  template:
    metadata:
      labels:
        app: cnpg-mcp-server
    spec:
      serviceAccountName: cnpg-mcp-server
      containers:
      - name: mcp-server
        image: your-registry/cnpg-mcp-server:latest
        ports:
        - containerPort: 3000
          name: http
        envFrom:
        - configMapRef:
            name: cnpg-mcp-oidc-config
        env:
        - name: PYTHONUNBUFFERED
          value: "1"
        livenessProbe:
          httpGet:
            path: /health
            port: 3000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 3000
          initialDelaySeconds: 5
          periodSeconds: 10
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
---
apiVersion: v1
kind: Service
metadata:
  name: cnpg-mcp-server
  namespace: default
spec:
  selector:
    app: cnpg-mcp-server
  ports:
  - port: 3000
    targetPort: 3000
    name: http
  type: ClusterIP
```

### Ingress with TLS

For production, expose the service via Ingress with TLS:

```yaml
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: cnpg-mcp-server
  namespace: default
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - mcp.example.com
    secretName: cnpg-mcp-tls
  rules:
  - host: mcp.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: cnpg-mcp-server
            port:
              number: 3000
```

## Testing

### 1. Obtain an Access Token

#### Using OAuth2 Client Credentials Flow

```bash
# Example with curl (adjust for your IdP)
TOKEN_RESPONSE=$(curl -X POST https://auth.example.com/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=your-client-id" \
  -d "client_secret=your-client-secret" \
  -d "audience=mcp-api")

TOKEN=$(echo $TOKEN_RESPONSE | jq -r '.access_token')
```

#### Using Authorization Code Flow

Use your IdP's login flow to obtain a token. This typically involves:

1. Navigate to authorization URL
2. Login and consent
3. Exchange authorization code for access token

### 2. Test Health Endpoint (No Auth Required)

```bash
curl http://localhost:3000/health
```

Expected response:
```json
{"status": "healthy", "service": "cnpg-mcp-server"}
```

### 3. Test OAuth Metadata Endpoint

```bash
curl http://localhost:3000/.well-known/oauth-authorization-server
```

Expected response:
```json
{
  "issuer": "https://auth.example.com",
  "jwks_uri": "https://auth.example.com/.well-known/jwks.json",
  "scopes_supported": ["openid"],
  ...
}
```

### 4. Test Authenticated MCP Endpoint

Using the test inspector:

```bash
# Save token to file
echo "$TOKEN" > token.txt

# Test HTTP mode with authentication
./test-inspector.sh --transport http \
  --url http://localhost:3000 \
  --token-file token.txt

# Or with token inline
./test-inspector.sh --transport http \
  --url http://localhost:3000 \
  --token "$TOKEN"

# Test stdio mode (no auth needed)
./test-inspector.sh --transport stdio
```

Using curl:

```bash
# Make authenticated request to MCP endpoint
curl -X POST http://localhost:3000/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "method": "tools/list",
    "params": {}
  }'
```

## DCR Proxy Setup

If your IdP doesn't support Dynamic Client Registration (DCR), you can use a DCR proxy.

### Option 1: Use Existing DCR Proxy

If you have a DCR proxy service, configure it:

```bash
export DCR_PROXY_URL=https://dcr-proxy.example.com/register
```

### Option 2: Deploy Your Own DCR Proxy

A simple DCR proxy can be implemented as a service that:

1. Receives DCR requests (RFC 7591)
2. Translates them to your IdP's client registration API
3. Returns a properly formatted DCR response

Example implementation outline:

```python
# dcr_proxy.py (pseudocode)
from fastapi import FastAPI, Request
import httpx

app = FastAPI()

@app.post("/register")
async def register_client(request: Request):
    dcr_request = await request.json()

    # Translate DCR request to IdP-specific format
    idp_request = {
        "client_name": dcr_request.get("client_name"),
        "redirect_uris": dcr_request.get("redirect_uris"),
        # ... other mappings
    }

    # Register with IdP
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://your-idp.example.com/api/clients",
            json=idp_request,
            headers={"Authorization": "Bearer admin-token"}
        )
        idp_client = response.json()

    # Return DCR-compliant response
    return {
        "client_id": idp_client["client_id"],
        "client_secret": idp_client["client_secret"],
        "registration_access_token": "...",
        # ... other fields
    }
```

## Security Best Practices

### 1. Use HTTPS/TLS

**Always** run the MCP server behind TLS in production:

- Use a reverse proxy (nginx, Traefik) with TLS certificates
- In Kubernetes, use Ingress with cert-manager for automatic certificate management
- Never expose HTTP endpoints directly to the internet

### 2. Validate Token Claims

The server validates:
- **Issuer (`iss`)**: Must match configured `OIDC_ISSUER`
- **Audience (`aud`)**: Must match configured `OIDC_AUDIENCE`
- **Expiration (`exp`)**: Token must not be expired
- **Signature**: Must be valid according to JWKS

### 3. Use Short-Lived Tokens

Configure your IdP to issue short-lived access tokens:
- Recommended: 15-60 minutes
- Use refresh tokens for long-lived sessions

### 4. Monitor and Log

Enable access logging to track:
- Failed authentication attempts
- Token validation errors
- Unusual access patterns

### 5. Principle of Least Privilege

- Grant only necessary Kubernetes RBAC permissions to the MCP server
- Use namespace isolation
- Consider separate service accounts for different environments

## Troubleshooting

### Error: "Missing Authorization header"

**Cause:** Request doesn't include `Authorization` header.

**Solution:** Include the header:
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" ...
```

### Error: "Invalid issuer"

**Cause:** Token `iss` claim doesn't match `OIDC_ISSUER`.

**Solution:** Verify your token:
```bash
# Decode JWT (header and payload only, signature not verified)
echo "YOUR_TOKEN" | cut -d. -f2 | base64 -d | jq
```

Check that `iss` matches your configuration.

### Error: "Invalid audience"

**Cause:** Token `aud` claim doesn't match `OIDC_AUDIENCE`.

**Solution:**
1. Check token claims (see above)
2. Verify IdP configuration includes correct audience
3. Ensure `OIDC_AUDIENCE` environment variable matches IdP config

### Error: "Token verification failed"

**Cause:** JWT signature validation failed.

**Possible causes:**
- Token is expired
- Token was signed with different key
- JWKS cache is stale (rare)

**Solution:**
1. Check token expiration:
   ```bash
   echo "YOUR_TOKEN" | cut -d. -f2 | base64 -d | jq '.exp'
   # Compare with current time: date +%s
   ```
2. Verify JWKS URI is correct
3. Restart server to refresh JWKS cache

### Error: "Failed to discover JWKS URI"

**Cause:** Server can't fetch OIDC configuration from issuer.

**Solution:**
1. Verify issuer URL is accessible:
   ```bash
   curl https://your-issuer/.well-known/openid-configuration
   ```
2. Manually set `OIDC_JWKS_URI` if discovery isn't supported

### OIDC Not Enabled

**Symptom:** Server starts with warning about insecure mode.

**Cause:** `OIDC_ISSUER` environment variable not set.

**Solution:** Set required environment variables:
```bash
export OIDC_ISSUER=https://auth.example.com
export OIDC_AUDIENCE=mcp-api
./start-http.sh
```

## Example Configurations

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
export OIDC_ISSUER=https://login.microsoftonline.com/your-tenant-id/v2.0
export OIDC_AUDIENCE=api://mcp-api
```

### Google

```bash
export OIDC_ISSUER=https://accounts.google.com
export OIDC_AUDIENCE=your-client-id.apps.googleusercontent.com
```

### Okta

```bash
export OIDC_ISSUER=https://your-org.okta.com/oauth2/default
export OIDC_AUDIENCE=api://mcp-api
```

## Client Configuration

### Simple Case: Server with DCR Enabled

If your MCP server is already deployed with OIDC and DCR (Dynamic Client Registration) enabled, client configuration is straightforward:

**For Claude Desktop:**

```json
{
  "mcpServers": {
    "cnpg": {
      "url": "https://mcp-api.example.com/mcp"
    }
  }
}
```

That's it! The MCP client will:
1. Discover OAuth configuration from `/.well-known/oauth-authorization-server`
2. Auto-register via DCR (if needed)
3. Obtain and refresh tokens automatically

**For MCP Inspector:**

```bash
./test-inspector.sh --transport http --url https://mcp-api.example.com
```

The inspector will handle authentication automatically through the OAuth flow.

**For other MCP clients:**

Just provide the server URL. The MCP SDK handles OAuth discovery and authentication:

```python
from mcp import ClientSession, HttpServerParameters

async with ClientSession(
    HttpServerParameters(url="https://mcp-api.example.com/mcp")
) as session:
    await session.initialize()
    # Use session...
```

### Advanced: Manual Token Management

**When to use manual token management:**
- Your IdP doesn't support DCR
- You need service-to-service authentication
- You're using client credentials flow
- You're debugging authentication issues

### Obtaining Access Tokens Manually

MCP clients need JWT access tokens to authenticate with the server. The method depends on your IdP and client type.

#### Auth0 - Machine-to-Machine (M2M) Client

1. **Create M2M Application in Auth0:**
   - Go to Applications > Create Application
   - Choose "Machine to Machine Applications"
   - Authorize for your API (the one with your audience)
   - Note the Client ID and Client Secret

2. **Get Access Token using Client Credentials:**
   ```bash
   curl -X POST https://YOUR_DOMAIN.auth0.com/oauth/token \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "grant_type=client_credentials" \
     -d "client_id=YOUR_CLIENT_ID" \
     -d "client_secret=YOUR_CLIENT_SECRET" \
     -d "audience=YOUR_API_AUDIENCE" \
     | jq -r '.access_token'
   ```

3. **Save token to file:**
   ```bash
   # Get and save token
   curl -X POST https://YOUR_DOMAIN.auth0.com/oauth/token \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "grant_type=client_credentials" \
     -d "client_id=YOUR_CLIENT_ID" \
     -d "client_secret=YOUR_CLIENT_SECRET" \
     -d "audience=YOUR_API_AUDIENCE" \
     | jq -r '.access_token' > token.txt

   # Verify token was saved
   cat token.txt | cut -d. -f2 | base64 -d 2>/dev/null | jq
   ```

#### Keycloak - Service Account

1. **Create Confidential Client:**
   - Clients > Create
   - Access Type: Confidential
   - Service Accounts Enabled: ON
   - Standard Flow Enabled: OFF

2. **Get Access Token:**
   ```bash
   curl -X POST https://keycloak.example.com/realms/REALM/protocol/openid-connect/token \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "grant_type=client_credentials" \
     -d "client_id=YOUR_CLIENT_ID" \
     -d "client_secret=YOUR_CLIENT_SECRET" \
     | jq -r '.access_token' > token.txt
   ```

#### Azure AD - App Registration

1. **Create App Registration:**
   - Azure Portal > Azure Active Directory > App registrations
   - New registration
   - Certificates & secrets > New client secret

2. **Get Access Token:**
   ```bash
   curl -X POST https://login.microsoftonline.com/YOUR_TENANT_ID/oauth2/v2.0/token \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "grant_type=client_credentials" \
     -d "client_id=YOUR_CLIENT_ID" \
     -d "client_secret=YOUR_CLIENT_SECRET" \
     -d "scope=api://YOUR_API/.default" \
     | jq -r '.access_token' > token.txt
   ```

#### Okta - OAuth 2.0 Client

1. **Create Application:**
   - Applications > Create App Integration
   - API Services (for M2M)
   - Note Client ID and Client Secret

2. **Get Access Token:**
   ```bash
   curl -X POST https://YOUR_ORG.okta.com/oauth2/default/v1/token \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "grant_type=client_credentials" \
     -d "client_id=YOUR_CLIENT_ID" \
     -d "client_secret=YOUR_CLIENT_SECRET" \
     -d "scope=mcp-api" \
     | jq -r '.access_token' > token.txt
   ```

### Testing with MCP Inspector

After obtaining a token, test your server using the MCP Inspector tool:

```bash
# Test with token file
./test-inspector.sh --transport http \
  --url https://mcp-api.example.com \
  --token-file token.txt

# Or with token directly
./test-inspector.sh --transport http \
  --url https://mcp-api.example.com \
  --token "eyJhbGciOiJSUzI1NiIs..."
```

The inspector will:
1. Connect to your MCP server via HTTP
2. Include the JWT token in Authorization header
3. List available tools, resources, and prompts
4. Allow interactive testing

**Test locally with port-forward:**
```bash
# Port forward from Kubernetes
kubectl port-forward -n default svc/cnpg-mcp 4204:4204

# Test via localhost
./test-inspector.sh --transport http \
  --url http://localhost:4204 \
  --token-file token.txt
```

See `README_TEST_INSPECTOR.md` for detailed testing instructions.

### Advanced: Manual Token Configuration

#### Claude Desktop with Manual Tokens

If you need to manually manage tokens (e.g., for service accounts or debugging):

**Location of config file:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

**Configuration with environment variable:**
```json
{
  "mcpServers": {
    "cnpg": {
      "url": "https://mcp-api.example.com/mcp",
      "transport": {
        "type": "http",
        "headers": {
          "Authorization": "Bearer ${MCP_TOKEN_CNPG}"
        }
      }
    }
  }
}
```

**Obtain and set token:**
```bash
# Get token from Auth0 (or your IdP)
TOKEN=$(curl -X POST https://YOUR_DOMAIN.auth0.com/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "audience=YOUR_API_AUDIENCE" \
  | jq -r '.access_token')

# Set environment variable
export MCP_TOKEN_CNPG="$TOKEN"

# Launch Claude Desktop
open -a "Claude"
```

**Important:** Tokens expire! See "Token Refresh Strategies" below.

#### Other MCP Clients with Manual Tokens

**Generic HTTP Transport Configuration:**
```json
{
  "servers": {
    "cnpg": {
      "url": "https://mcp-api.example.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_JWT_TOKEN"
      }
    }
  }
}
```

**Client SDKs:**
- MCP Python SDK: Use `StdioServerParameters` for local or `HttpServerParameters` for remote
- MCP TypeScript SDK: Use appropriate transport configuration

**Example with MCP Python Client:**
```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# For HTTP transport with auth
async with stdio_client(
    StdioServerParameters(
        command="python",
        args=["-m", "mcp_proxy"],  # Your token-refreshing proxy
        env={"MCP_UPSTREAM": "https://mcp-api.example.com/mcp"}
    )
) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        # Use session...
```

### Token Management Best Practices

1. **Short Token Lifetime**: Use tokens with 15-60 minute expiration
2. **Automatic Refresh**: Implement token refresh in your client
3. **Secure Storage**: Never commit tokens to git
4. **Environment Variables**: Use env vars for sensitive credentials
5. **Rotation**: Rotate client secrets regularly
6. **Monitoring**: Log token usage and failures

### Token Refresh Strategies

#### Strategy 1: Credential Helper Script

Create a helper that Claude Desktop can call:
```bash
#!/bin/bash
# ~/.mcp/get-token.sh
curl -s -X POST https://YOUR_DOMAIN.auth0.com/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=$MCP_CLIENT_ID" \
  -d "client_secret=$MCP_CLIENT_SECRET" \
  -d "audience=$MCP_AUDIENCE" \
  | jq -r '.access_token'
```

Configure Claude Desktop to execute this script periodically.

#### Strategy 2: Token Refresh Proxy

Run a local service that handles token refresh:
```python
# token_proxy.py
from fastapi import FastAPI, Request
import httpx
import os
from datetime import datetime, timedelta

app = FastAPI()
token_cache = {"token": None, "expires": None}

async def get_fresh_token():
    if token_cache["expires"] and datetime.now() < token_cache["expires"]:
        return token_cache["token"]

    # Fetch new token
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{os.getenv('AUTH0_DOMAIN')}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": os.getenv("CLIENT_ID"),
                "client_secret": os.getenv("CLIENT_SECRET"),
                "audience": os.getenv("AUDIENCE")
            }
        )
        data = response.json()
        token_cache["token"] = data["access_token"]
        token_cache["expires"] = datetime.now() + timedelta(seconds=data["expires_in"] - 60)
        return data["access_token"]

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(path: str, request: Request):
    token = await get_fresh_token()

    async with httpx.AsyncClient() as client:
        response = await client.request(
            method=request.method,
            url=f"{os.getenv('MCP_UPSTREAM')}/{path}",
            headers={"Authorization": f"Bearer {token}"},
            content=await request.body()
        )
        return Response(content=response.content, status_code=response.status_code)
```

Then configure Claude Desktop to connect to `http://localhost:8080` instead of the remote server.

## Additional Resources

- [RFC 6749 - OAuth 2.0 Authorization Framework](https://tools.ietf.org/html/rfc6749)
- [RFC 7519 - JSON Web Token (JWT)](https://tools.ietf.org/html/rfc7519)
- [RFC 7591 - OAuth 2.0 Dynamic Client Registration](https://tools.ietf.org/html/rfc7591)
- [RFC 8414 - OAuth 2.0 Authorization Server Metadata](https://tools.ietf.org/html/rfc8414)
- [MCP Inspector Documentation](https://github.com/modelcontextprotocol/inspector)
- [Claude Desktop Configuration Guide](https://docs.anthropic.com/claude/docs)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
