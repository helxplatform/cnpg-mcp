# OIDC Authentication Setup Guide

This guide explains how to configure OIDC/OAuth2 authentication for the CloudNativePG MCP Server when running in HTTP transport mode.

## Overview

The CloudNativePG MCP Server supports OIDC authentication for secure remote access. Key features:

- **JWT Bearer Token Verification**: Uses RS256/ES256 signatures
- **JWKS-based Public Key Discovery**: Automatic key rotation support
- **Non-DCR IdP Support**: Works with IdPs that don't support Dynamic Client Registration via a DCR proxy
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
    cert-manager.io/cluster-issuer: letsencrypt-prod
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

## Additional Resources

- [RFC 6749 - OAuth 2.0 Authorization Framework](https://tools.ietf.org/html/rfc6749)
- [RFC 7519 - JSON Web Token (JWT)](https://tools.ietf.org/html/rfc7519)
- [RFC 7591 - OAuth 2.0 Dynamic Client Registration](https://tools.ietf.org/html/rfc7591)
- [RFC 8414 - OAuth 2.0 Authorization Server Metadata](https://tools.ietf.org/html/rfc8414)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
