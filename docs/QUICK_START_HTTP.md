# Quick Start: HTTP Mode with OIDC Authentication

This guide gets you up and running with the CloudNativePG MCP Server in HTTP mode with OIDC authentication in under 5 minutes.

## Prerequisites

- Python 3.11+
- Access to an OIDC/OAuth2 identity provider (Auth0, Keycloak, Okta, etc.)
- Kubernetes cluster with CloudNativePG operator installed

## 5-Minute Setup

### Step 1: Install Dependencies (1 min)

```bash
pip install -r requirements.txt
```

### Step 2: Configure OIDC (2 min)

Set your OIDC provider details:

```bash
# Required
export OIDC_ISSUER=https://auth.example.com
export OIDC_AUDIENCE=mcp-api

# Optional (auto-discovered if not set)
# export OIDC_JWKS_URI=https://auth.example.com/.well-known/jwks.json
# export DCR_PROXY_URL=https://dcr-proxy.example.com/register
```

**Don't have OIDC configured yet?** Run in development mode (insecure):
```bash
# Skip OIDC for local testing only
unset OIDC_ISSUER OIDC_AUDIENCE
```

### Step 3: Start Server (30 sec)

```bash
./start-http.sh
```

You should see:
```
✓ Server is running on http://0.0.0.0:3000
✓ OIDC authentication enabled (or WARNING if not configured)
```

### Step 4: Test It (1.5 min)

#### Test Health (No Auth Required)
```bash
curl http://localhost:3000/health
# Response: {"status":"healthy","service":"cnpg-mcp-server"}
```

#### Test OAuth Metadata
```bash
curl http://localhost:3000/.well-known/oauth-authorization-server | jq
```

#### Get Access Token
Obtain a JWT from your OIDC provider. Example using curl (adjust for your IdP):

```bash
# Example: Client Credentials Flow
TOKEN=$(curl -X POST https://auth.example.com/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "audience=mcp-api" \
  | jq -r '.access_token')

echo $TOKEN > token.txt
```

#### Test Authenticated Endpoints
```bash
# Test with MCP Inspector (HTTP mode)
./test-inspector.sh --transport http \
  --url http://localhost:3000 \
  --token-file token.txt

# Or test stdio mode locally
./test-inspector.sh --transport stdio
```

## What's Next?

### For Local Development
- See `OIDC_SETUP.md` for IdP-specific configuration
- Use `test-inspector.py` to explore available tools
- Check logs for authentication issues

### For Production Deployment
1. **Build Docker image:**
   ```bash
   docker build -t your-registry/cnpg-mcp-server:latest .
   docker push your-registry/cnpg-mcp-server:latest
   ```

2. **Update Kubernetes manifests:**
   - Edit `kubernetes-deployment-oidc.yaml`
   - Set your OIDC configuration in ConfigMap
   - Update image reference

3. **Deploy to Kubernetes:**
   ```bash
   kubectl apply -f kubernetes-deployment-oidc.yaml
   ```

4. **Configure Ingress:**
   - Set up TLS certificates (use cert-manager)
   - Update host in Ingress spec
   - Apply ingress configuration

5. **Test in production:**
   ```bash
   curl https://mcp-api.example.com/health

   python test-inspector.py --url https://mcp-api.example.com \
     --token-file token.txt \
     list-tools
   ```

## Common Issues

### "Missing Authorization header"
You forgot to include the token. Add `--token` or `--token-file`:
```bash
./test-inspector.sh --transport http \
  --url http://localhost:3000 \
  --token-file token.txt
```

### "Invalid issuer" or "Invalid audience"
Your token's `iss` or `aud` claims don't match your configuration. Verify:
```bash
# Decode token (header and payload only)
echo "$TOKEN" | cut -d. -f2 | base64 -d | jq
```

Check that `iss` matches `OIDC_ISSUER` and `aud` matches `OIDC_AUDIENCE`.

### "Token verification failed"
- Token might be expired (check `exp` claim)
- JWKS URI might be wrong
- Token signed with different key

Verify token:
```bash
# Check expiration
echo "$TOKEN" | cut -d. -f2 | base64 -d | jq '.exp'
# Compare with current time
date +%s
```

### Server runs in "INSECURE mode"
`OIDC_ISSUER` is not set. For production, you must configure OIDC:
```bash
export OIDC_ISSUER=https://auth.example.com
export OIDC_AUDIENCE=mcp-api
./start-http.sh
```

## File Reference

- `auth_oidc.py` - OIDC authentication implementation
- `cnpg_mcp_server.py` - Main server (HTTP mode at line ~2077)
- `start-http.sh` - Convenience script for HTTP mode
- `test-inspector.sh` - Testing tool using MCP Inspector (supports stdio and HTTP)
- `OIDC_SETUP.md` - **Complete setup guide** (start here for OIDC config)
- `kubernetes-deployment-oidc.yaml` - Production K8s deployment
- `Dockerfile` - Container image definition

## Getting Help

1. **OIDC Setup**: See `OIDC_SETUP.md` for detailed instructions
2. **Troubleshooting**: Check `OIDC_SETUP.md` troubleshooting section
3. **Architecture**: See `HTTP_OIDC_IMPLEMENTATION.md` for technical details
4. **Development**: See `CLAUDE.md` for developer guidance

## IdP Quick Links

### Auth0
```bash
export OIDC_ISSUER=https://YOUR-TENANT.auth0.com
export OIDC_AUDIENCE=YOUR-API-IDENTIFIER
```

### Keycloak
```bash
export OIDC_ISSUER=https://keycloak.example.com/realms/YOUR-REALM
export OIDC_AUDIENCE=mcp-api
```

### Okta
```bash
export OIDC_ISSUER=https://YOUR-ORG.okta.com/oauth2/default
export OIDC_AUDIENCE=api://mcp-api
```

### Azure AD
```bash
export OIDC_ISSUER=https://login.microsoftonline.com/YOUR-TENANT-ID/v2.0
export OIDC_AUDIENCE=api://mcp-api
```

### Google
```bash
export OIDC_ISSUER=https://accounts.google.com
export OIDC_AUDIENCE=YOUR-CLIENT-ID.apps.googleusercontent.com
```

---

**Ready to go deeper?** Read `OIDC_SETUP.md` for comprehensive setup instructions.
