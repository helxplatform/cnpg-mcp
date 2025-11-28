#!/usr/bin/env python3
"""
CloudNativePG MCP Test Server (OIDC Auth)

Test endpoint for the CloudNativePG MCP server using standard OIDC authentication.
This server accepts Auth0 JWT tokens directly (no MCP token issuance).

This is deployed as a sidecar container alongside the main FastMCP OAuth server,
allowing both authentication methods to coexist:
- Main server (port 3000): FastMCP OAuth proxy issuing MCP tokens
- Test server (port 3001): Standard OIDC accepting Auth0 JWT tokens

Both servers share the same 12 tool implementations from cnpg_tools.py.
"""

import argparse
import logging
import sys
import os

from fastmcp import FastMCP
import uvicorn
from starlette.middleware import Middleware
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

# Import OIDC auth
from auth_oidc import OIDCAuthProvider, OIDCAuthMiddleware

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

mcp = FastMCP("cloudnative-pg-test")

# ============================================================================
# Register Tools
# ============================================================================

# Register all 12 tools by decorating the imported functions
# These are the same tool implementations used by the main server

@mcp.tool()
async def list_postgres_clusters_tool(
    namespace: str = None,
    all_namespaces: bool = False,
    detail_level: str = "concise"
):
    """List all PostgreSQL clusters managed by CloudNativePG."""
    return await list_postgres_clusters(namespace, all_namespaces, detail_level)


@mcp.tool()
async def get_cluster_status_tool(
    cluster_name: str,
    namespace: str = None,
    detail_level: str = "detailed"
):
    """Get detailed status of a specific PostgreSQL cluster."""
    return await get_cluster_status(cluster_name, namespace, detail_level)


@mcp.tool()
async def create_postgres_cluster_tool(
    cluster_name: str,
    instances: int = 3,
    storage_size: str = "1Gi",
    postgres_version: str = "16",
    namespace: str = None,
    dry_run: bool = False
):
    """Create a new PostgreSQL cluster with high availability configuration."""
    return await create_postgres_cluster(
        cluster_name, instances, storage_size, postgres_version, namespace, dry_run
    )


@mcp.tool()
async def scale_postgres_cluster_tool(
    cluster_name: str,
    instances: int,
    namespace: str = None
):
    """Scale a PostgreSQL cluster by changing the number of instances."""
    return await scale_postgres_cluster(cluster_name, instances, namespace)


@mcp.tool()
async def delete_postgres_cluster_tool(
    cluster_name: str,
    namespace: str = None,
    confirm: bool = False
):
    """Delete a PostgreSQL cluster."""
    return await delete_postgres_cluster(cluster_name, namespace, confirm)


@mcp.tool()
async def list_postgres_roles_tool(
    cluster_name: str,
    namespace: str = None
):
    """List all PostgreSQL roles (users) in a cluster."""
    return await list_postgres_roles(cluster_name, namespace)


@mcp.tool()
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


@mcp.tool()
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
    return await update_postgres_role(
        cluster_name, role_name, login, superuser, inherit,
        createdb, createrole, replication, reset_password, namespace
    )


@mcp.tool()
async def delete_postgres_role_tool(
    cluster_name: str,
    role_name: str,
    namespace: str = None,
    confirm: bool = False
):
    """Delete a PostgreSQL role and its associated secret."""
    return await delete_postgres_role(cluster_name, role_name, namespace, confirm)


@mcp.tool()
async def list_postgres_databases_tool(
    cluster_name: str,
    namespace: str = None
):
    """List all databases managed by Database CRDs."""
    return await list_postgres_databases(cluster_name, namespace)


@mcp.tool()
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


@mcp.tool()
async def delete_postgres_database_tool(
    database_name: str,
    namespace: str = None,
    confirm: bool = False
):
    """Delete a Database CRD (actual deletion depends on reclaim policy)."""
    return await delete_postgres_database(database_name, namespace, confirm)


logger.info("✅ Registered 12 tools with test MCP server")

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
# Main Entry Point
# ============================================================================

def main():
    """Main entry point for the test server."""
    parser = argparse.ArgumentParser(
        description="CloudNativePG MCP Test Server (OIDC Auth)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "3001")),
        help="Port to listen on (default: 3001)"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)"
    )

    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("CloudNativePG MCP Test Server (OIDC Auth)")
    logger.info("=" * 70)
    logger.info(f"Listening on: {args.host}:{args.port}")
    logger.info(f"Endpoint: /test")
    logger.info(f"Auth: Standard OIDC (Auth0 JWT tokens)")
    logger.info("Tools: 12 CloudNativePG management tools")
    logger.info("=" * 70)

    # Create OIDC auth provider
    logger.info("🔐 Initializing OIDC authentication...")
    oidc_provider = OIDCAuthProvider()
    logger.info(f"   Issuer: {oidc_provider.issuer}")
    logger.info(f"   Audience: {oidc_provider.audience}")

    # Create FastMCP HTTP app
    app = mcp.http_app(transport="http", path="/test")

    # Add OIDC middleware
    logger.info("🔒 Adding OIDC authentication middleware...")
    app.add_middleware(
        OIDCAuthMiddleware,
        auth_provider=oidc_provider,
        exclude_paths=["/healthz", "/readyz"]
    )

    # Add health check routes
    app.add_route("/healthz", liveness_check)
    app.add_route("/readyz", readiness_check)

    logger.info("✅ Test server ready")
    logger.info("")
    logger.info("To test with Auth0 JWT token:")
    logger.info("  1. Get token: ./test/get-user-token.py")
    logger.info("  2. Test: ./test/test-mcp.py --transport http \\")
    logger.info(f"           --url http://localhost:{args.port}/test \\")
    logger.info("           --token-file /tmp/user-token.txt")
    logger.info("")

    # Run server
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info"
    )


if __name__ == "__main__":
    main()
