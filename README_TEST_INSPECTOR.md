# Test Inspector Usage Guide

The `test-inspector.sh` script provides a unified way to test the CloudNativePG MCP Server in both stdio and HTTP transport modes using the official MCP Inspector.

## Quick Start

### Test Stdio Mode (Local Development)

```bash
# Default - tests stdio transport
./test-inspector.sh

# Or explicitly
./test-inspector.sh --transport stdio
```

This launches the MCP Inspector with the server running as a subprocess. Perfect for local development and testing.

### Test HTTP Mode (Production)

```bash
# Test HTTP with authentication
./test-inspector.sh --transport http \
  --url http://localhost:3000 \
  --token-file token.txt

# Or with inline token
./test-inspector.sh --transport http \
  --url http://localhost:3000 \
  --token "eyJhbGciOiJSUzI1NiIs..."

# Test remote endpoint
./test-inspector.sh --transport http \
  --url https://mcp-api.example.com \
  --token-file ~/.mcp/token.txt
```

## Options

```
-t, --transport <mode>    Transport mode: stdio (default) or http
-u, --url <url>          HTTP URL (default: http://localhost:3000)
--token <token>          JWT bearer token for HTTP mode
--token-file <file>      File containing JWT bearer token
-h, --help               Show help message
```

## Environment Variables

```bash
# Default HTTP URL
export MCP_HTTP_URL=https://mcp-api.example.com
./test-inspector.sh --transport http --token-file token.txt
```

## Examples

### Local Development (No Auth)

```bash
# Test stdio mode - server runs as subprocess
./test-inspector.sh --transport stdio

# Test HTTP mode without OIDC (development only!)
./test-inspector.sh --transport http --url http://localhost:3000
```

### Production Testing

```bash
# 1. Obtain JWT token from your IdP
# (Example using client credentials flow)
TOKEN=$(curl -X POST https://auth.example.com/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "audience=mcp-api" \
  | jq -r '.access_token')

# 2. Save to file
echo "$TOKEN" > token.txt

# 3. Test with inspector
./test-inspector.sh --transport http \
  --url https://mcp-api.example.com \
  --token-file token.txt
```

### Testing Different Environments

```bash
# Development
./test-inspector.sh --transport http \
  --url http://localhost:3000 \
  --token-file dev-token.txt

# Staging
./test-inspector.sh --transport http \
  --url https://mcp-staging.example.com \
  --token-file staging-token.txt

# Production
./test-inspector.sh --transport http \
  --url https://mcp.example.com \
  --token-file prod-token.txt
```

## Using the MCP Inspector

Once the inspector launches, you'll see a web interface at `http://localhost:5173` (or similar).

### Available Features:

1. **Resources Tab** - View available resources
2. **Prompts Tab** - Test prompts
3. **Tools Tab** - Execute MCP tools
4. **Notifications Tab** - View server notifications
5. **Settings** - Configure inspector options

### Testing Tools:

1. Navigate to the **Tools** tab
2. Select a tool (e.g., `list_postgres_clusters`)
3. Fill in parameters (JSON format)
4. Click "Execute"
5. View the response

Example tool calls:

```json
// list_postgres_clusters
{
  "namespace": "default"
}

// get_cluster_status
{
  "cluster_name": "my-cluster",
  "namespace": "default",
  "detail_level": "detailed"
}

// create_postgres_cluster
{
  "cluster_name": "test-cluster",
  "namespace": "default",
  "instances": 3,
  "storage_size": "10Gi"
}
```

## Troubleshooting

### "npx is not installed"

Install Node.js and npm:
```bash
# Ubuntu/Debian
sudo apt-get install nodejs npm

# macOS
brew install node

# Or download from https://nodejs.org/
```

### "Token file not found"

Ensure the token file exists and contains a valid JWT:
```bash
# Check file exists
ls -la token.txt

# View token content (should be a JWT)
cat token.txt

# Verify it's a valid JWT (should have 3 parts separated by dots)
cat token.txt | tr '.' '\n' | wc -l
# Should output: 3
```

### "Authorization failed" with HTTP mode

1. **Verify token is valid:**
   ```bash
   # Decode JWT to check claims
   echo "$TOKEN" | cut -d. -f2 | base64 -d | jq
   ```

2. **Check issuer matches:**
   ```bash
   # Token issuer should match OIDC_ISSUER
   echo "$TOKEN" | cut -d. -f2 | base64 -d | jq '.iss'
   ```

3. **Check audience matches:**
   ```bash
   # Token audience should match OIDC_AUDIENCE
   echo "$TOKEN" | cut -d. -f2 | base64 -d | jq '.aud'
   ```

4. **Check token is not expired:**
   ```bash
   # Check expiration
   echo "$TOKEN" | cut -d. -f2 | base64 -d | jq '.exp'
   # Compare with current time
   date +%s
   ```

### Inspector shows "Connection refused"

For HTTP mode:
1. Ensure the server is running:
   ```bash
   curl http://localhost:3000/health
   ```

2. Check server logs for errors

3. Verify OIDC configuration if authentication is required

For stdio mode:
1. Ensure Python and dependencies are installed
2. Verify you're in the correct directory
3. Check that `cnpg_mcp_server.py` exists

## Comparison with Old Test Inspector

The new `test-inspector.sh` uses the official MCP Inspector instead of a custom Python implementation:

### Old (Python-based):
```bash
python test-inspector.py --url http://localhost:3000 \
  --token-file token.txt \
  call-tool --tool list_postgres_clusters --params '{}'
```

### New (MCP Inspector):
```bash
./test-inspector.sh --transport http \
  --url http://localhost:3000 \
  --token-file token.txt
```

**Advantages:**
- ✅ Official MCP Inspector with web UI
- ✅ Visual tool testing and exploration
- ✅ Supports both stdio and HTTP modes
- ✅ Better error messages and debugging
- ✅ Real-time interaction with server
- ✅ No custom Python code to maintain

## See Also

- `OIDC_SETUP.md` - OIDC authentication configuration
- `QUICK_START_HTTP.md` - Quick start guide for HTTP mode
- `start-http.sh` - Script to start server in HTTP mode
- [MCP Inspector Documentation](https://github.com/modelcontextprotocol/inspector)
