# User Authentication Testing Guide

This guide explains how to test the CNPG MCP server with **user authentication** (not M2M client credentials).

## Why User Authentication?

The MCP server requires **user identity** for:
- Labeling Kubernetes resources with the user who created them
- Future: User authorization and access control
- Mimicking how Claude Desktop and other MCP clients authenticate

**Key Difference:**
- ❌ **M2M (Machine-to-Machine)**: Client credentials flow - identifies the *application*, not a user
- ✅ **User Authentication**: Authorization Code + PKCE flow - identifies the *person* using the application

## Quick Start

### 1. Set up Auth0 Configuration

Run the setup script to create all necessary Auth0 resources:

```bash
python bin/setup-auth0.py --token YOUR_AUTH0_MGMT_TOKEN
```

This creates:
- Management API client (for Auth0 API access)
- Test M2M client (for testing only)
- **User Auth client (SPA/Native with PKCE)** ← This is what you'll use!

### 2. Get a User Access Token

Use the Authorization Code Flow with PKCE (same as Claude Desktop):

```bash
./get-user-token.py
```

**What happens:**
1. Script starts local server on `http://localhost:8888`
2. Opens your browser to Auth0 login page
3. You log in with your Auth0 user credentials
4. Browser redirects to local server with authorization code
5. Script exchanges code for access token
6. Token saved to `user-token.txt`

**Token includes:**
- ✅ `openid` scope (required for user identity)
- ✅ User claims: `sub`, `email`, `name`
- ✅ API scopes: `mcp:read`, `mcp:write`

### 3. Test with MCP Inspector

```bash
./test-inspector.py --transport http \
  --url https://cnpg-mcp.wat.im \
  --token-file user-token.txt
```

## Understanding Token Contents

### M2M Token (Wrong for this use case):
```json
{
  "iss": "https://dev-xxx.auth0.com/",
  "sub": "4ymHp9JYKPqFE3XOu...",  // CLIENT ID (not a user!)
  "aud": "https://cnpg-mcp.wat.im/mcp",
  "scope": "mcp:read mcp:write",    // NO openid scope
  "azp": "4ymHp9JYKPqFE3XOu..."
}
```

### User Token (Correct):
```json
{
  "iss": "https://dev-xxx.auth0.com/",
  "sub": "auth0|123456",             // USER ID
  "aud": "https://cnpg-mcp.wat.im/mcp",
  "scope": "openid profile email mcp:read mcp:write",
  "email": "user@example.com",       // User email
  "name": "Jane Doe",                // User name
  "azp": "userAuthClientId..."
}
```

## Server Behavior

The MCP server:

1. **Validates JWT signature** using JWKS from Auth0
2. **Requires `openid` scope** (default parameter: `required_scope="openid"`)
3. **Extracts user identity** from claims:
   ```python
   user_id = request.state.auth_claims.get('sub')
   user_email = request.state.auth_claims.get('email')
   ```
4. **Future**: Labels Kubernetes resources with user identity

## Troubleshooting

### Error: "Required scope 'openid' not found in token"

**Cause:** You're using an M2M token (from `test_client`) instead of a user token.

**Fix:** Use `./get-user-token.py` to get a proper user token.

### Error: "unauthorized_client" during token exchange

**Cause:** User auth client doesn't have Authorization Code grant type enabled.

**Fix:** Re-run setup:
```bash
python bin/setup-auth0.py --token YOUR_TOKEN --recreate-client
```

### Error: "Callback URL mismatch"

**Cause:** `http://localhost:8888/callback` not in allowed callbacks.

**Fix:** The setup script should add this automatically. If not, manually add in Auth0 dashboard:
1. Applications → MCP User Auth Client
2. Settings → Allowed Callback URLs
3. Add: `http://localhost:8888/callback`

### Browser doesn't open automatically

**Fix:** Manually copy the URL from terminal and paste into browser.

## How Claude Desktop Would Authenticate

Claude Desktop uses the exact same flow:

1. **Authorization Code Flow with PKCE**
2. Opens system browser for login
3. Listens on `http://localhost:<port>/callback`
4. Exchanges authorization code for tokens
5. Stores refresh token for subsequent sessions
6. Includes `Authorization: Bearer <token>` header on all MCP requests

The `get-user-token.py` script implements this same flow for testing purposes.

## Files

- `get-user-token.py` - Get user tokens (Authorization Code + PKCE)
- `test-inspector.py` - Test with MCP Inspector
- `auth0-config.json` - Auth0 configuration (includes `user_auth_client`)
- `user-token.txt` - Saved access token
- `refresh-token.txt` - Saved refresh token (if available)

## Next Steps

Once user authentication is working, the server can be enhanced to:

1. **Extract user identity** from token claims
2. **Label Kubernetes resources**:
   ```yaml
   metadata:
     labels:
       mcp.user: user@example.com
       mcp.user.id: auth0|123456
   ```
3. **Implement authorization** via ConfigMap or LDAP:
   - Check if user is allowed to create/modify resources
   - Apply user-specific quotas
   - Audit logging
