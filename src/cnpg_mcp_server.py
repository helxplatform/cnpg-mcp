#!/usr/bin/env python3
"""
CloudNativePG MCP Server (FastMCP OAuth)

Main MCP server for CloudNativePG management using FastMCP's OAuth proxy.
This server issues MCP tokens after Auth0 authentication.

This runs as the primary container in a sidecar deployment alongside the
test server:
- Main server (port 3000): FastMCP OAuth proxy issuing MCP tokens
- Test server (port 3001): Standard OIDC accepting Auth0 JWT tokens

Both servers share the same 12 tool implementations from cnpg_tools.py.

Transport Modes:
- stdio: Communication over stdin/stdout (default, for Claude Desktop)
- http: HTTP server with OAuth for remote access
"""

import argparse
import logging
import sys
import os

from fastmcp import FastMCP
import uvicorn
from starlette.routing import Route
from starlette.responses import JSONResponse

# Import shared tools
from cnpg_tools import (
    list_postgres_clusters,
    get_cluster_status,
    create_postgres_cluster,
    scale_postgres_cluster,
    delete_postgres_cluster,
    list_postgres_roles,
    create_postgres_role,
    update_postgres_role,
    delete_postgres_role,
    list_postgres_databases,
    create_postgres_database,
    delete_postgres_database,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:     %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger(__name__)

# Set log levels for external libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# ============================================================================
# FastMCP Server Initialization
# ============================================================================

mcp = FastMCP("cloudnative-pg")

# ============================================================================
# Register Tools
# ============================================================================

# Register all 12 tools by decorating the imported functions
# These are the same tool implementations used by the test server

@mcp.tool(name="list_postgres_clusters")
async def list_postgres_clusters_tool(
    namespace: str = None,
    all_namespaces: bool = False,
    detail_level: str = "concise"
):
    """List all PostgreSQL clusters managed by CloudNativePG."""
    return await list_postgres_clusters(namespace, all_namespaces, detail_level)


@mcp.tool(name="get_cluster_status")
async def get_cluster_status_tool(
    name: str,
    namespace: str = None,
    detail_level: str = "detailed"
):
    """Get detailed status of a specific PostgreSQL cluster."""
    return await get_cluster_status(name, namespace, detail_level)


@mcp.tool(name="create_postgres_cluster")
async def create_postgres_cluster_tool(
    name: str,
    instances: int = 3,
    storage_size: str = "1Gi",
    postgres_version: str = "16",
    namespace: str = None,
    dry_run: bool = False
):
    """Create a new PostgreSQL cluster with high availability configuration."""
    return await create_postgres_cluster(
        name, instances, storage_size, postgres_version, namespace, dry_run
    )


@mcp.tool(name="scale_postgres_cluster")
async def scale_postgres_cluster_tool(
    name: str,
    instances: int,
    namespace: str = None
):
    """Scale a PostgreSQL cluster by changing the number of instances."""
    return await scale_postgres_cluster(name, instances, namespace)


@mcp.tool(name="delete_postgres_cluster")
async def delete_postgres_cluster_tool(
    name: str,
    namespace: str = None,
    confirm: bool = False
):
    """Delete a PostgreSQL cluster."""
    return await delete_postgres_cluster(name, namespace, confirm)


@mcp.tool(name="list_postgres_roles")
async def list_postgres_roles_tool(
    cluster_name: str,
    namespace: str = None
):
    """List all PostgreSQL roles (users) in a cluster."""
    return await list_postgres_roles(cluster_name, namespace)


@mcp.tool(name="create_postgres_role")
async def create_postgres_role_tool(
    cluster_name: str,
    role_name: str,
    login: bool = True,
    superuser: bool = False,
    inherit: bool = True,
    createdb: bool = False,
    createrole: bool = False,
    replication: bool = False,
    namespace: str = None,
    dry_run: bool = False
):
    """Create a new PostgreSQL role (user) with auto-generated password."""
    return await create_postgres_role(
        cluster_name, role_name, login, superuser, inherit,
        createdb, createrole, replication, namespace, dry_run
    )


@mcp.tool(name="update_postgres_role")
async def update_postgres_role_tool(
    cluster_name: str,
    role_name: str,
    login: bool = None,
    superuser: bool = None,
    inherit: bool = None,
    createdb: bool = None,
    createrole: bool = None,
    replication: bool = None,
    reset_password: bool = False,
    namespace: str = None
):
    """Update an existing PostgreSQL role's attributes and optionally reset password."""
    # Generate new password if reset_password is True
    from cnpg_tools import generate_password
    password = generate_password() if reset_password else None

    return await update_postgres_role(
        cluster_name, role_name, login, superuser, inherit,
        createdb, createrole, replication, password, namespace
    )


@mcp.tool(name="delete_postgres_role")
async def delete_postgres_role_tool(
    cluster_name: str,
    role_name: str,
    namespace: str = None,
    confirm: bool = False
):
    """Delete a PostgreSQL role and its associated secret."""
    return await delete_postgres_role(cluster_name, role_name, namespace, confirm)


@mcp.tool(name="list_postgres_databases")
async def list_postgres_databases_tool(
    cluster_name: str,
    namespace: str = None
):
    """List all databases managed by Database CRDs."""
    return await list_postgres_databases(cluster_name, namespace)


@mcp.tool(name="create_postgres_database")
async def create_postgres_database_tool(
    cluster_name: str,
    database_name: str,
    owner: str,
    reclaim_policy: str = "retain",
    namespace: str = None,
    dry_run: bool = False
):
    """Create a new database using Database CRD."""
    return await create_postgres_database(
        cluster_name, database_name, owner, reclaim_policy, namespace, dry_run
    )


@mcp.tool(name="delete_postgres_database")
async def delete_postgres_database_tool(
    database_name: str,
    namespace: str = None,
    confirm: bool = False
):
    """Delete a Database CRD (actual deletion depends on reclaim policy)."""
    return await delete_postgres_database(database_name, namespace, confirm)


logger.info("Registered 12 tools with main MCP server")

# ============================================================================
# Health Check Endpoints
# ============================================================================

async def liveness_check(request):
    """Kubernetes liveness probe endpoint."""
    return JSONResponse({"status": "alive"})


async def readiness_check(request):
    """Kubernetes readiness probe endpoint."""
    return JSONResponse({"status": "ready"})


# ============================================================================
# Transport Implementations
# ============================================================================

async def run_stdio_transport():
    """Run server in stdio mode (for Claude Desktop)."""
    logger.info("=" * 70)
    logger.info("CloudNativePG MCP Server (stdio mode)")
    logger.info("=" * 70)
    logger.info("Tools: 12 CloudNativePG management tools")
    logger.info("=" * 70)

    # Run stdio transport
    await mcp.run_stdio_async()


def run_http_transport(host: str, port: int):
    """Run server in HTTP mode with FastMCP OAuth."""
    from auth_fastmcp import create_auth0_oauth_proxy, get_auth_config_summary, load_oidc_config_from_file

    logger.info("Initializing FastMCP OAuth Proxy for Auth0...")

    # Load configuration
    config = load_oidc_config_from_file() or {}
    issuer = config.get("issuer") or os.getenv("OIDC_ISSUER") or ""
    audience = config.get("audience") or os.getenv("OIDC_AUDIENCE") or ""
    client_id = config.get("client_id") or os.getenv("AUTH0_CLIENT_ID") or ""
    public_url = config.get("public_url") or os.getenv("PUBLIC_URL") or ""

    # Create OAuth Proxy (handles token issuance)
    auth_proxy = create_auth0_oauth_proxy()

    # Log configuration summary
    config_summary = get_auth_config_summary(issuer, audience, client_id, public_url)
    logger.info("=" * 80)
    logger.info("FastMCP OAuth Configuration:")
    logger.info("=" * 80)
    for key, value in config_summary.items():
        logger.info(f"  {key}: {value}")
    logger.info("=" * 80)

    # Set OAuth on mcp instance
    mcp.auth = auth_proxy

    # Create app with OAuth at /mcp endpoint
    app = mcp.http_app(transport="http", path="/mcp")

    # Add health check routes
    app.add_route("/healthz", liveness_check)
    app.add_route("/readyz", readiness_check)

    logger.info("")
    logger.info("=" * 80)
    logger.info("Server Configuration:")
    logger.info("=" * 80)
    logger.info(f"  Listening on: {host}:{port}")
    logger.info(f"  MCP Endpoint: /mcp")
    logger.info(f"  Auth: FastMCP OAuth Proxy (issues MCP tokens)")
    logger.info("  Tools: 12 CloudNativePG management tools")
    logger.info(f"  OAuth Discovery: /.well-known/oauth-authorization-server")
    logger.info(f"  Client Registration: /register")
    logger.info("=" * 80)
    logger.info("")
    logger.info("To get an MCP token:")
    logger.info(f"  ./test/get-mcp-token.py --url http://{host}:{port}")
    logger.info("")
    logger.info("To test with MCP token:")
    logger.info("  ./test/test-mcp.py --transport http \\")
    logger.info(f"    --url http://{host}:{port}/mcp \\")
    logger.info("    --token-file /tmp/mcp-token.txt")
    logger.info("")

    # Run server
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Main entry point with transport selection."""
    parser = argparse.ArgumentParser(
        description="CloudNativePG MCP Server"
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode: stdio (default) or http"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "3000")),
        help="Port for HTTP transport (default: 3000)"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for HTTP transport (default: 0.0.0.0)"
    )

    args = parser.parse_args()

    if args.transport == "stdio":
        import asyncio
        asyncio.run(run_stdio_transport())
    else:
        run_http_transport(args.host, args.port)


if __name__ == "__main__":
    main()
