#!/usr/bin/env python3
"""
MCP Authentication Proxy

This proxy sits between MCP Inspector and your authenticated MCP server.
Inspector connects to the proxy (no auth needed), and the proxy forwards
requests to the real server with automatic Authorization header injection.

Usage:
    1. Get a user token: ./get-user-token.py
    2. Start the proxy: ./mcp-auth-proxy.py
    3. Use Inspector normally: npx @modelcontextprotocol/inspector --transport http --url http://localhost:8889/mcp

The proxy automatically adds the Authorization header, so no copy-paste needed!
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route, Mount
import uvicorn


class AuthProxy:
    """Proxy that adds authentication to MCP requests."""

    def __init__(self, backend_url: str, token: str):
        self.backend_url = backend_url.rstrip('/')
        self.token = token
        self.client = httpx.AsyncClient(timeout=300.0)

    async def proxy_request(self, request: Request) -> Response:
        """Forward request to backend with authentication."""

        # Build backend URL
        path = request.url.path
        query = str(request.url.query)
        backend_url = f"{self.backend_url}{path}"
        if query:
            backend_url += f"?{query}"

        # Copy headers from request, add Authorization
        headers = dict(request.headers)
        headers.pop('host', None)  # Remove host header
        headers['Authorization'] = f'Bearer {self.token}'

        # Get request body
        body = await request.body()

        print(f"→ {request.method} {path}")

        try:
            # Forward request to backend
            backend_response = await self.client.request(
                method=request.method,
                url=backend_url,
                headers=headers,
                content=body,
            )

            # Return response
            print(f"← {backend_response.status_code} {path}")

            return Response(
                content=backend_response.content,
                status_code=backend_response.status_code,
                headers=dict(backend_response.headers),
            )

        except httpx.RequestError as e:
            print(f"✗ Request failed: {e}")
            return Response(
                content=json.dumps({"error": "proxy_error", "message": str(e)}),
                status_code=502,
                headers={"Content-Type": "application/json"}
            )

    async def health(self, request: Request) -> Response:
        """Health check endpoint."""
        return Response(
            content=json.dumps({
                "status": "ok",
                "backend": self.backend_url,
                "authenticated": bool(self.token)
            }),
            headers={"Content-Type": "application/json"}
        )


def load_token() -> Optional[str]:
    """Load user token from file."""
    token_file = Path("user-token.txt")
    if token_file.exists():
        return token_file.read_text().strip()
    return None


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="MCP Authentication Proxy - Add auth headers automatically",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example Usage:

  1. Get a user token (if you don't have one):
     ./get-user-token.py

  2. Start the proxy:
     ./mcp-auth-proxy.py --backend https://cnpg-mcp.wat.im

  3. Use Inspector with the proxy (NO AUTH NEEDED!):
     npx @modelcontextprotocol/inspector --transport http --url http://localhost:8889/mcp

  4. Inspector UI will connect without requiring any headers!

The proxy automatically injects the Authorization header from user-token.txt.
"""
    )

    parser.add_argument(
        '--backend',
        default='https://cnpg-mcp.wat.im',
        help='Backend MCP server URL (default: https://cnpg-mcp.wat.im)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=8889,
        help='Local proxy port (default: 8889)'
    )
    parser.add_argument(
        '--token',
        help='JWT token (default: read from user-token.txt)'
    )
    parser.add_argument(
        '--token-file',
        default='user-token.txt',
        help='Token file path (default: user-token.txt)'
    )

    args = parser.parse_args()

    # Load token
    if args.token:
        token = args.token.strip()
        print(f"✅ Using token from command line")
    else:
        token = load_token()
        if token:
            print(f"✅ Loaded token from {args.token_file}")
        else:
            print(f"❌ No token found in {args.token_file}")
            print()
            print("To get a user token, run:")
            print("  ./get-user-token.py")
            print()
            return 1

    # Create proxy
    proxy = AuthProxy(args.backend, token)

    # Create Starlette app
    routes = [
        Route('/{path:path}', proxy.proxy_request, methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS']),
        Route('/health', proxy.health, methods=['GET']),
    ]

    app = Starlette(routes=routes)

    # Print instructions
    print()
    print("=" * 70)
    print("MCP Authentication Proxy")
    print("=" * 70)
    print()
    print(f"Backend MCP Server: {args.backend}")
    print(f"Proxy listening on:  http://localhost:{args.port}")
    print()
    print("✅ Authorization header will be added automatically!")
    print()
    print("=" * 70)
    print("Use Inspector (no auth needed!):")
    print("=" * 70)
    print()
    print(f"  npx @modelcontextprotocol/inspector \\")
    print(f"    --transport http \\")
    print(f"    --url http://localhost:{args.port}/mcp")
    print()
    print("Or visit the UI directly:")
    print(f"  http://localhost:6274/?transport=streamable-http&url=http://localhost:{args.port}/mcp")
    print()
    print("=" * 70)
    print()
    print("Press Ctrl+C to stop the proxy")
    print()

    # Run proxy
    try:
        uvicorn.run(
            app,
            host='127.0.0.1',
            port=args.port,
            log_level='warning'
        )
    except KeyboardInterrupt:
        print()
        print("Proxy stopped")

    return 0


if __name__ == "__main__":
    exit(main())
