# Adding HTTP/SSE Transport

This guide explains how to add HTTP/SSE transport to the CloudNativePG MCP server when you're ready to support remote access and multiple clients.

## Why Add HTTP Transport?

**Current (stdio):**
- ✅ Simple, secure, easy to test
- ❌ Single client per server
- ❌ Must be on same machine

**With HTTP/SSE:**
- ✅ Multiple clients can connect
- ✅ Remote access from anywhere
- ✅ Deploy as shared service
- ✅ Better for teams and production

## Prerequisites

1. Your stdio implementation is working well
2. You need remote access or multi-client support
3. You're ready to handle authentication and security

## Step-by-Step Implementation

### Step 1: Install Dependencies

Uncomment the HTTP dependencies in `requirements.txt`:

```bash
pip install 'mcp[sse]' starlette uvicorn python-multipart
```

### Step 2: Implement the HTTP Transport Function

Replace the `run_http_transport()` function in `cnpg_mcp_server.py`:

```python
async def run_http_transport(host: str = "0.0.0.0", port: int = 3000):
    """Run the MCP server using HTTP/SSE transport."""
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import Response
    import uvicorn
    
    print(f"Starting CloudNativePG MCP server on http://{host}:{port}", file=sys.stderr)
    
    # Create SSE transport
    sse_transport = SseServerTransport("/messages")
    
    # SSE endpoint - clients connect here for event stream
    async def handle_sse(request):
        async with sse_transport.connect_sse(
            request.scope,
            request.receive,
            request._send,
        ) as streams:
            await mcp.run(
                streams[0],
                streams[1],
                mcp.create_initialization_options()
            )
        return Response()
    
    # Messages endpoint - clients POST requests here
    async def handle_messages(request):
        await sse_transport.handle_post_message(request)
        return Response()
    
    # Health check endpoint (optional but recommended)
    async def health_check(request):
        return Response(
            content='{"status": "healthy"}',
            media_type="application/json"
        )
    
    # Create Starlette app
    app = Starlette(
        debug=False,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=handle_messages, methods=["POST"]),
            Route("/health", endpoint=health_check),
        ]
    )
    
    # Run the server
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()
```

### Step 3: Test Locally

Start the server:
```bash
python cnpg_mcp_server.py --transport http --port 3000
```

Test with curl:
```bash
# Health check
curl http://localhost:3000/health

# SSE connection (will stream events)
curl -N http://localhost:3000/sse
```

### Step 4: Add Authentication (Production Required)

Add authentication middleware:

```python
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.authentication import (
    AuthenticationBackend, AuthCredentials, SimpleUser
)
import secrets

class TokenAuthBackend(AuthenticationBackend):
    def __init__(self, valid_tokens: set):
        self.valid_tokens = valid_tokens
    
    async def authenticate(self, conn):
        # Get token from header or query param
        token = conn.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            token = conn.query_params.get("token", "")
        
        if token in self.valid_tokens:
            return AuthCredentials(["authenticated"]), SimpleUser("user")
        
        return None

# Create auth backend with valid tokens
valid_tokens = {
    "your-secret-token-here",  # Load from environment!
    # Add more tokens as needed
}

# Add to Starlette app
app = Starlette(
    debug=False,
    routes=[...],
    middleware=[
        Middleware(
            AuthenticationMiddleware,
            backend=TokenAuthBackend(valid_tokens)
        )
    ]
)

# Protect endpoints
from starlette.authentication import requires

@requires("authenticated")
async def handle_sse(request):
    # ... same as before
```

### Step 5: Add TLS Support (Production Required)

**Option A: Use reverse proxy (Recommended)**

Deploy behind nginx or traefik:
```nginx
server {
    listen 443 ssl;
    server_name mcp.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

**Option B: Built-in TLS**

```python
config = uvicorn.Config(
    app,
    host=host,
    port=port,
    ssl_keyfile="/path/to/key.pem",
    ssl_certfile="/path/to/cert.pem",
)
```

### Step 6: Update Client Configuration

For clients connecting via HTTP:

```json
{
  "mcpServers": {
    "cloudnative-pg": {
      "url": "https://mcp.example.com:3000",
      "headers": {
        "Authorization": "Bearer your-token-here"
      }
    }
  }
}
```

### Step 7: Deploy to Kubernetes

Update `kubernetes-deployment.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: cnpg-mcp-server
  namespace: default
spec:
  selector:
    app: cnpg-mcp-server
  ports:
  - protocol: TCP
    port: 3000
    targetPort: 3000
  type: ClusterIP
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cnpg-mcp-server
spec:
  replicas: 2  # Can now scale horizontally!
  template:
    spec:
      containers:
      - name: mcp-server
        image: your-registry/cnpg-mcp-server:latest
        command: ["python", "cnpg_mcp_server.py"]
        args: ["--transport", "http", "--port", "3000"]
        env:
        - name: AUTH_TOKENS
          valueFrom:
            secretKeyRef:
              name: mcp-auth-tokens
              key: tokens
        ports:
        - containerPort: 3000
          protocol: TCP
        livenessProbe:
          httpGet:
            path: /health
            port: 3000
          initialDelaySeconds: 10
          periodSeconds: 30
```

Expose with Ingress:
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: cnpg-mcp-ingress
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
  - hosts:
    - mcp.example.com
    secretName: mcp-tls
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

## Security Checklist

Before deploying HTTP transport to production:

- [ ] Authentication is required for all endpoints
- [ ] TLS/HTTPS is enabled
- [ ] Tokens are loaded from secrets, not hardcoded
- [ ] Rate limiting is configured
- [ ] CORS is properly configured (if needed)
- [ ] Health check endpoint is unauthenticated
- [ ] Audit logging is enabled
- [ ] Network policies are configured in Kubernetes
- [ ] Secrets are rotated regularly
- [ ] Monitor for suspicious access patterns

## Testing HTTP Transport

### Manual Testing

```bash
# Start server
python cnpg_mcp_server.py --transport http --port 3000

# In another terminal - health check
curl http://localhost:3000/health

# Connect to SSE stream
curl -N -H "Authorization: Bearer your-token" \
  http://localhost:3000/sse

# Send a message (requires MCP client implementation)
curl -X POST http://localhost:3000/messages \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}'
```

### Programmatic Testing

```python
import httpx
import asyncio

async def test_http_server():
    async with httpx.AsyncClient() as client:
        # Health check
        response = await client.get("http://localhost:3000/health")
        print(f"Health: {response.json()}")
        
        # Connect to SSE
        async with client.stream(
            "GET",
            "http://localhost:3000/sse",
            headers={"Authorization": "Bearer your-token"}
        ) as response:
            async for line in response.aiter_lines():
                print(f"Event: {line}")

asyncio.run(test_http_server())
```

## Troubleshooting

### "Connection refused"
- Check server is running: `curl http://localhost:3000/health`
- Verify port is correct
- Check firewall rules

### "401 Unauthorized"
- Verify token in Authorization header
- Check token is in valid_tokens set
- Ensure token is not expired (if using JWTs)

### "SSE stream disconnects"
- Check client timeout settings
- Verify network stability
- Look for server errors in logs

### "Can't connect from other machines"
- Verify host is `0.0.0.0` not `127.0.0.1`
- Check firewall/security groups
- Ensure port is exposed in Kubernetes Service

## Performance Considerations

- **Connection pooling**: HTTP allows connection reuse
- **Horizontal scaling**: Run multiple server instances
- **Load balancing**: Use Kubernetes Service or ingress
- **Caching**: Consider caching cluster status queries
- **Rate limiting**: Protect against abuse
- **Metrics**: Add Prometheus metrics for monitoring

## Migration Strategy

To migrate from stdio to HTTP smoothly:

1. **Keep both transports** during transition
2. **Test HTTP thoroughly** in staging environment
3. **Migrate clients gradually** one at a time
4. **Monitor for issues** with both transports running
5. **Deprecate stdio** once all clients migrated

## When NOT to Use HTTP Transport

- **Single user**: stdio is simpler
- **Local development**: stdio is faster to test
- **No remote access needed**: stdio is more secure
- **Simple use case**: stdio has less overhead

## Summary

HTTP/SSE transport enables:
- ✅ Remote access
- ✅ Multiple concurrent clients
- ✅ Production deployments
- ✅ Team collaboration

But requires:
- ⚠️ Authentication and authorization
- ⚠️ TLS/HTTPS setup
- ⚠️ More operational complexity
- ⚠️ Security considerations

Start with stdio, migrate to HTTP when you need the features!
