#!/usr/bin/env python3
"""
MCP Authentication Proxy

This proxy sits between MCP Inspector and your authenticated MCP server.
Inspector connects to the proxy (no auth needed), and the proxy forwards
requests to the real server with automatic Authorization header injection.

Usage:
    1. Get a user token: ./test/get-user-token.py
    2. Start the proxy: ./test/mcp-auth-proxy.py
    3. Use Inspector normally: npx @modelcontextprotocol/inspector --transport http --url http://localhost:8889/mcp

The proxy automatically adds the Authorization header, so no copy-paste needed!
"""

import asyncio
import json
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

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
        # Force HTTP/1.1 to match curl behavior
        self.client = httpx.AsyncClient(timeout=300.0, http2=False)

    async def proxy_request(self, request: Request) -> Response:
        """Forward request to backend with authentication."""

        path = request.url.path

        # Handle CORS preflight requests (don't forward to backend)
        if request.method == "OPTIONS":
            print(f"\n→ OPTIONS {path} (CORS preflight)", flush=True)
            print(f"← 200 (CORS headers)", flush=True)
            return Response(
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization",
                    "Access-Control-Max-Age": "3600",
                }
            )

        # Build backend URL
        query = str(request.url.query)
        backend_url = f"{self.backend_url}{path}"
        if query:
            backend_url += f"?{query}"

        # Copy headers from request, add Authorization and proper Host
        headers = dict(request.headers)

        # Remove headers we'll replace
        headers.pop('host', None)
        headers.pop('authorization', None)  # Remove any existing auth header
        headers.pop('Authorization', None)

        # Set correct Host header for backend
        backend_host = urlparse(self.backend_url).netloc
        headers['Host'] = backend_host
        headers['Authorization'] = f'Bearer {self.token}'

        # Get request body
        body = await request.body()

        # Debug output
        print(f"\n→ {request.method} {path}", flush=True)
        print(f"  Incoming headers from Inspector:", flush=True)
        for key, value in request.headers.items():
            print(f"    {key}: {value[:100] if len(value) > 100 else value}", flush=True)
        print(f"  URL: {backend_url}", flush=True)
        print(f"  Outgoing headers to backend:", flush=True)
        for key, value in headers.items():
            if key.lower() == 'authorization':
                print(f"    {key}: Bearer {self.token[:20]}...{self.token[-10:]}", flush=True)
            else:
                print(f"    {key}: {value[:100] if len(value) > 100 else value}", flush=True)
        print(f"  Body: {len(body)} bytes", flush=True)
        if len(body) < 300:
            print(f"  {body.decode('utf-8', errors='replace')}", flush=True)

        try:
            # Forward request to backend
            backend_response = await self.client.request(
                method=request.method,
                url=backend_url,
                headers=headers,
                content=body,
            )

            # Return response
            print(f"← {backend_response.status_code} {path}", flush=True)
            print(f"  Content-Type: {backend_response.headers.get('content-type', 'not set')}", flush=True)

            # Read response content once
            response_content = backend_response.content

            # Show response body for debugging
            try:
                response_preview = response_content.decode('utf-8')[:500] if response_content else "no body"
                if backend_response.status_code >= 400:
                    print(f"  Error: {response_preview}", flush=True)
                else:
                    print(f"  Response: {response_preview}", flush=True)
            except:
                print(f"  Response: {len(response_content)} bytes (binary)", flush=True)

            # Add CORS headers to response
            response_headers = dict(backend_response.headers)
            response_headers["Access-Control-Allow-Origin"] = "*"
            response_headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
            response_headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"

            return Response(
                content=response_content,
                status_code=backend_response.status_code,
                headers=response_headers,
            )

        except httpx.RequestError as e:
            print(f"✗ Request failed: {e}")
            return Response(
                content=json.dumps({"error": "proxy_error", "message": str(e)}),
                status_code=502,
                headers={
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                }
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


def load_token(token_file_path: str = "/tmp/mcp-user-token.txt") -> Optional[str]:
    """Load user token from file."""
    token_file = Path(token_file_path)
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
     ./test/get-user-token.py

  2. Start the proxy:
     ./test/mcp-auth-proxy.py --backend https://cnpg-mcp.wat.im

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
        default='/tmp/mcp-user-token.txt',
        help='Token file path (default: /tmp/mcp-user-token.txt)'
    )

    args = parser.parse_args()

    # Load token
    if args.token:
        token = args.token.strip()
        print(f"✅ Using token from command line")
    else:
        token = load_token(args.token_file)
        if token:
            print(f"✅ Loaded token from {args.token_file}")
        else:
            print(f"❌ No token found in {args.token_file}")
            print()
            print("To get a user token, run:")
            print("  ./test/get-user-token.py")
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
