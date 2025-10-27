#!/usr/bin/env python3
"""
CloudNativePG MCP Server

An MCP server for managing PostgreSQL clusters using the CloudNativePG operator.
Provides tools for creating, managing, and monitoring PostgreSQL clusters in Kubernetes.

Transport Modes:
- stdio: Communication over stdin/stdout (default, for Claude Desktop)
- http: HTTP server with SSE for remote access (future implementation)
"""

import asyncio
import json
import sys
import argparse
from typing import Any, Dict, List, Optional, Literal
from datetime import datetime

from mcp.server import Server
from mcp.types import Tool, TextContent, Resource, Prompt
from pydantic import BaseModel, Field
from kubernetes import client, config
from kubernetes.client.rest import ApiException

# ============================================================================
# Configuration and Constants
# ============================================================================

CHARACTER_LIMIT = 25000
CNPG_GROUP = "postgresql.cnpg.io"
CNPG_VERSION = "v1"
CNPG_PLURAL = "clusters"

# Transport mode (set via CLI args)
TRANSPORT_MODE = "stdio"  # or "http"

# ============================================================================
# Server Initialization
# ============================================================================

# Initialize MCP server
mcp = Server("cloudnative-pg")

# Kubernetes clients (initialized lazily)
custom_api: Optional[client.CustomObjectsApi] = None
core_api: Optional[client.CoreV1Api] = None
_k8s_init_attempted = False
_k8s_init_error: Optional[str] = None

def get_kubernetes_clients() -> tuple[client.CustomObjectsApi, client.CoreV1Api]:
    """
    Get or initialize Kubernetes API clients (lazy initialization).

    This allows the MCP server to start even if Kubernetes is not available,
    and provides clear error messages when tools are called without K8s access.
    """
    global custom_api, core_api, _k8s_init_attempted, _k8s_init_error

    # Return cached clients if already initialized
    if custom_api is not None and core_api is not None:
        return custom_api, core_api

    # If we already tried and failed, return the cached error
    if _k8s_init_attempted and _k8s_init_error:
        raise Exception(_k8s_init_error)

    # Try to initialize
    _k8s_init_attempted = True

    try:
        config.load_incluster_config()
        print("Loaded in-cluster Kubernetes config", file=sys.stderr)
    except config.ConfigException:
        try:
            config.load_kube_config()
            print("Loaded kubeconfig from file", file=sys.stderr)
        except Exception as e:
            _k8s_init_error = (
                f"Failed to load Kubernetes configuration: {e}\n\n"
                "Make sure you have:\n"
                "1. A valid ~/.kube/config file, OR\n"
                "2. KUBECONFIG environment variable set, OR\n"
                "3. Running inside a Kubernetes cluster with proper service account\n\n"
                "You can test your kubectl access with: kubectl cluster-info"
            )
            print(f"Kubernetes initialization failed: {_k8s_init_error}", file=sys.stderr)
            raise Exception(_k8s_init_error)

    custom_api = client.CustomObjectsApi()
    core_api = client.CoreV1Api()

    return custom_api, core_api


# ============================================================================
# Utility Functions
# ============================================================================

def truncate_response(content: str, max_length: int = CHARACTER_LIMIT) -> str:
    """Truncate response content to stay within character limits."""
    if len(content) <= max_length:
        return content
    
    truncated = content[:max_length - 100]
    return f"{truncated}\n\n... (truncated, {len(content) - max_length} characters omitted)"


def format_error_message(error: Exception, context: str = "") -> str:
    """Format error messages in an LLM-friendly, actionable way."""
    if isinstance(error, ApiException):
        status = error.status
        reason = error.reason
        body = json.loads(error.body) if error.body else {}
        message = body.get('message', str(error))
        
        suggestion = ""
        if status == 404:
            suggestion = "The resource does not exist. Try listing available resources first or check the namespace."
        elif status == 403:
            suggestion = "Permission denied. Verify that the service account has proper RBAC permissions for CloudNativePG resources."
        elif status == 409:
            suggestion = "Resource conflict. The resource may already exist or there's a version conflict."
        elif status == 422:
            suggestion = "Invalid resource specification. Check the cluster specification against CloudNativePG API documentation."
        
        result = f"Kubernetes API Error ({status} {reason})"
        if context:
            result += f" while {context}"
        result += f": {message}"
        if suggestion:
            result += f"\n\nSuggestion: {suggestion}"
        
        return result
    
    return f"Error{' ' + context if context else ''}: {str(error)}"


async def get_cnpg_cluster(namespace: str, name: str) -> Dict[str, Any]:
    """Get a CloudNativePG cluster resource."""
    try:
        custom_api, _ = get_kubernetes_clients()
        cluster = await asyncio.to_thread(
            custom_api.get_namespaced_custom_object,
            group=CNPG_GROUP,
            version=CNPG_VERSION,
            namespace=namespace,
            plural=CNPG_PLURAL,
            name=name
        )
        return cluster
    except ApiException as e:
        raise Exception(format_error_message(e, f"getting cluster {namespace}/{name}"))


async def list_cnpg_clusters(namespace: Optional[str] = None) -> List[Dict[str, Any]]:
    """List CloudNativePG cluster resources."""
    try:
        custom_api, _ = get_kubernetes_clients()
        if namespace:
            result = await asyncio.to_thread(
                custom_api.list_namespaced_custom_object,
                group=CNPG_GROUP,
                version=CNPG_VERSION,
                namespace=namespace,
                plural=CNPG_PLURAL
            )
        else:
            result = await asyncio.to_thread(
                custom_api.list_cluster_custom_object,
                group=CNPG_GROUP,
                version=CNPG_VERSION,
                plural=CNPG_PLURAL
            )
        return result.get('items', [])
    except ApiException as e:
        raise Exception(format_error_message(e, "listing clusters"))


def format_cluster_status(cluster: Dict[str, Any], detail_level: str = "concise") -> str:
    """Format cluster status in a human-readable way."""
    metadata = cluster.get('metadata', {})
    spec = cluster.get('spec', {})
    status = cluster.get('status', {})
    
    name = metadata.get('name', 'unknown')
    namespace = metadata.get('namespace', 'unknown')
    instances = spec.get('instances', 0)
    
    phase = status.get('phase', 'Unknown')
    ready_instances = status.get('readyInstances', 0)
    current_primary = status.get('currentPrimary', 'unknown')
    
    result = f"**Cluster: {namespace}/{name}**\n"
    result += f"- Status: {phase}\n"
    result += f"- Instances: {ready_instances}/{instances} ready\n"
    result += f"- Current Primary: {current_primary}\n"
    
    if detail_level == "detailed":
        # Add more detailed information
        pg_version = spec.get('imageName', 'unknown')
        storage_size = spec.get('storage', {}).get('size', 'unknown')
        
        result += f"- PostgreSQL Version: {pg_version}\n"
        result += f"- Storage Size: {storage_size}\n"
        
        # Add conditions
        conditions = status.get('conditions', [])
        if conditions:
            result += "\n**Conditions:**\n"
            for condition in conditions:
                ctype = condition.get('type', 'Unknown')
                cstatus = condition.get('status', 'Unknown')
                reason = condition.get('reason', '')
                message = condition.get('message', '')
                result += f"- {ctype}: {cstatus}"
                if reason:
                    result += f" ({reason})"
                if message and detail_level == "detailed":
                    result += f"\n  {message}"
                result += "\n"
    
    return result


# ============================================================================
# Pydantic Models for Tool Inputs
# ============================================================================

class ListClustersInput(BaseModel):
    """Input for listing PostgreSQL clusters."""
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace to list clusters from. If not provided, lists clusters from all namespaces."
    )
    detail_level: Literal["concise", "detailed"] = Field(
        "concise",
        description="Level of detail in the response. 'concise' for overview, 'detailed' for comprehensive information."
    )


class GetClusterStatusInput(BaseModel):
    """Input for getting cluster status."""
    namespace: str = Field(
        ...,
        description="Kubernetes namespace where the cluster exists.",
        examples=["default", "production", "postgres-system"]
    )
    name: str = Field(
        ...,
        description="Name of the CloudNativePG cluster.",
        examples=["my-postgres-cluster", "production-db"]
    )
    detail_level: Literal["concise", "detailed"] = Field(
        "concise",
        description="Level of detail in the response."
    )


class CreateClusterInput(BaseModel):
    """Input for creating a new PostgreSQL cluster."""
    namespace: str = Field(
        ...,
        description="Kubernetes namespace where the cluster will be created.",
        examples=["default", "production"]
    )
    name: str = Field(
        ...,
        description="Name for the new cluster. Must be a valid Kubernetes resource name.",
        examples=["my-postgres-cluster", "production-db"],
        pattern=r'^[a-z0-9]([-a-z0-9]*[a-z0-9])?$'
    )
    instances: int = Field(
        3,
        description="Number of PostgreSQL instances in the cluster (for high availability).",
        ge=1,
        le=10
    )
    storage_size: str = Field(
        "10Gi",
        description="Storage size for each instance (e.g., '10Gi', '100Gi').",
        examples=["10Gi", "50Gi", "100Gi"]
    )
    postgres_version: str = Field(
        "16",
        description="PostgreSQL major version to use.",
        examples=["14", "15", "16"]
    )
    storage_class: Optional[str] = Field(
        None,
        description="Kubernetes storage class to use. If not specified, uses the cluster default."
    )


class ScaleClusterInput(BaseModel):
    """Input for scaling a cluster."""
    namespace: str = Field(..., description="Kubernetes namespace of the cluster.")
    name: str = Field(..., description="Name of the cluster to scale.")
    instances: int = Field(
        ...,
        description="New number of instances.",
        ge=1,
        le=10
    )


# ============================================================================
# MCP Tools - Implementation Functions
# ============================================================================

async def list_postgres_clusters(
    namespace: Optional[str] = None,
    detail_level: Literal["concise", "detailed"] = "concise"
) -> str:
    """
    List all PostgreSQL clusters managed by CloudNativePG.
    
    This tool retrieves information about PostgreSQL clusters in the Kubernetes cluster.
    Use this to discover available clusters, check their health status, and understand
    the current state of your PostgreSQL infrastructure.
    
    Args:
        namespace: Kubernetes namespace to list clusters from. If not provided, lists
                  clusters from all namespaces. Use None for cluster-wide listing.
        detail_level: Level of detail in the response. Use 'concise' for a quick
                     overview or 'detailed' for comprehensive information including
                     conditions, resources, and configurations.
    
    Returns:
        A formatted string containing cluster information. Returns human-readable
        status information for each cluster including name, namespace, health status,
        number of ready instances, and current primary pod.
    
    Examples:
        - List all clusters: list_postgres_clusters()
        - List clusters in a namespace: list_postgres_clusters(namespace="production")
        - Get detailed information: list_postgres_clusters(detail_level="detailed")
    
    Error Handling:
        - If RBAC permissions are insufficient, ensure the service account has 'get' and
          'list' permissions for postgresql.cnpg.io/clusters resources.
        - If no clusters are found, returns a message indicating empty results.
    """
    try:
        clusters = await list_cnpg_clusters(namespace)
        
        if not clusters:
            scope = f"in namespace '{namespace}'" if namespace else "cluster-wide"
            return f"No PostgreSQL clusters found {scope}."
        
        result = f"Found {len(clusters)} PostgreSQL cluster(s):\n\n"
        
        for cluster in clusters:
            result += format_cluster_status(cluster, detail_level) + "\n"
        
        return truncate_response(result)
    
    except Exception as e:
        return format_error_message(e, "listing PostgreSQL clusters")


async def get_cluster_status(
    namespace: str,
    name: str,
    detail_level: Literal["concise", "detailed"] = "concise"
) -> str:
    """
    Get detailed status information for a specific PostgreSQL cluster.
    
    This tool retrieves comprehensive information about a CloudNativePG cluster,
    including its current state, health conditions, replica status, and configuration.
    Use this to troubleshoot issues, verify cluster health, or get detailed insights
    into a specific cluster's operation.
    
    Args:
        namespace: Kubernetes namespace where the cluster exists. This is required
                  as cluster names are only unique within a namespace.
        name: Name of the CloudNativePG cluster resource.
        detail_level: Level of detail. 'concise' provides essential status information,
                     'detailed' includes conditions, events, resource usage, and full
                     configuration.
    
    Returns:
        Formatted string with cluster status information including phase, ready instances,
        primary pod, PostgreSQL version, storage configuration, and detailed conditions
        if requested.
    
    Examples:
        - get_cluster_status(namespace="production", name="main-db")
        - get_cluster_status(namespace="default", name="test-db", detail_level="detailed")
    
    Error Handling:
        - Returns 404 if cluster doesn't exist: Double-check the namespace and name.
        - Returns 403 if permissions are insufficient: Verify RBAC permissions for the
          postgresql.cnpg.io/clusters resource.
    """
    try:
        cluster = await get_cnpg_cluster(namespace, name)
        result = format_cluster_status(cluster, detail_level)
        return truncate_response(result)
    
    except Exception as e:
        return format_error_message(e, f"getting cluster status for {namespace}/{name}")


async def create_postgres_cluster(
    namespace: str,
    name: str,
    instances: int = 3,
    storage_size: str = "10Gi",
    postgres_version: str = "16",
    storage_class: Optional[str] = None
) -> str:
    """
    Create a new PostgreSQL cluster with CloudNativePG.
    
    This tool creates a new high-availability PostgreSQL cluster with the specified
    configuration. The cluster will automatically set up replication, backups, and
    monitoring. This is a comprehensive workflow tool that handles the entire cluster
    creation process.
    
    Args:
        namespace: Kubernetes namespace where the cluster will be created. The namespace
                  must exist before creating the cluster.
        name: Name for the new cluster. Must be a valid Kubernetes resource name
              (lowercase alphanumeric characters or '-', starting and ending with
              alphanumeric character).
        instances: Number of PostgreSQL instances. Use 1 for development, 3+ for
                  production high availability. Default is 3.
        storage_size: Storage size per instance using Kubernetes quantity format
                     (e.g., '10Gi', '100Gi', '1Ti'). Consider your data size and
                     growth projections.
        postgres_version: PostgreSQL major version (e.g., '14', '15', '16').
                         CloudNativePG will use the latest minor version available.
        storage_class: Kubernetes storage class for persistent volumes. If not specified,
                      uses the cluster's default storage class. Use fast storage (SSD)
                      for production databases.
    
    Returns:
        Success message with cluster details if creation succeeds, or detailed error
        message with suggestions if it fails.
    
    Examples:
        - Simple cluster: create_postgres_cluster(namespace="default", name="my-db")
        - Production cluster: create_postgres_cluster(
            namespace="production",
            name="main-db",
            instances=5,
            storage_size="100Gi",
            postgres_version="16",
            storage_class="fast-ssd"
          )
    
    Error Handling:
        - 409 Conflict: Cluster with this name already exists. Choose a different name
          or delete the existing cluster first.
        - 422 Invalid: Check that all parameters meet CloudNativePG requirements.
        - 403 Forbidden: Ensure service account has 'create' permission for
          postgresql.cnpg.io/clusters.
    
    Note:
        Cluster creation is asynchronous. After creation, use get_cluster_status() to
        monitor the cluster until it reaches 'Cluster in healthy state' phase.
    """
    try:
        # Build the cluster specification
        cluster_spec = {
            "apiVersion": f"{CNPG_GROUP}/{CNPG_VERSION}",
            "kind": "Cluster",
            "metadata": {
                "name": name,
                "namespace": namespace
            },
            "spec": {
                "instances": instances,
                "imageName": f"ghcr.io/cloudnative-pg/postgresql:{postgres_version}",
                "storage": {
                    "size": storage_size
                },
                "postgresql": {
                    "parameters": {
                        "max_connections": "100",
                        "shared_buffers": "256MB"
                    }
                },
                "bootstrap": {
                    "initdb": {
                        "database": "app",
                        "owner": "app",
                        "secret": {
                            "name": f"{name}-app-user"
                        }
                    }
                }
            }
        }
        
        # Add storage class if specified
        if storage_class:
            cluster_spec["spec"]["storage"]["storageClass"] = storage_class

        # Create the cluster
        custom_api, _ = get_kubernetes_clients()
        result = await asyncio.to_thread(
            custom_api.create_namespaced_custom_object,
            group=CNPG_GROUP,
            version=CNPG_VERSION,
            namespace=namespace,
            plural=CNPG_PLURAL,
            body=cluster_spec
        )
        
        cluster_name = result['metadata']['name']
        return f"""Successfully created PostgreSQL cluster '{cluster_name}' in namespace '{namespace}'.

Configuration:
- Instances: {instances}
- PostgreSQL Version: {postgres_version}
- Storage Size: {storage_size}
{f'- Storage Class: {storage_class}' if storage_class else ''}

The cluster is now being provisioned. You can monitor its status using:
get_cluster_status(namespace="{namespace}", name="{cluster_name}")

Wait until the cluster reaches 'Cluster in healthy state' phase before connecting.
"""
    
    except Exception as e:
        return format_error_message(e, f"creating cluster {namespace}/{name}")


async def scale_postgres_cluster(
    namespace: str,
    name: str,
    instances: int
) -> str:
    """
    Scale a PostgreSQL cluster by changing the number of instances.
    
    This tool modifies the number of PostgreSQL instances in a cluster, allowing you
    to scale up for increased capacity or scale down to reduce resource usage.
    CloudNativePG handles the scaling process safely, ensuring data consistency.
    
    Args:
        namespace: Kubernetes namespace where the cluster exists.
        name: Name of the cluster to scale.
        instances: New number of instances (1-10). For high availability, use 3 or more.
    
    Returns:
        Success message if the scaling operation is initiated, or error details if it fails.
    
    Examples:
        - Scale up: scale_postgres_cluster(namespace="production", name="main-db", instances=5)
        - Scale down: scale_postgres_cluster(namespace="default", name="test-db", instances=1)
    
    Error Handling:
        - 404: Cluster not found. Verify namespace and name.
        - 422: Invalid instance count. Must be between 1 and 10.
        - Scaling is performed as a rolling update. Monitor with get_cluster_status().
    
    Note:
        Scaling is asynchronous. The cluster will gradually adjust to the new size.
        Use get_cluster_status() to monitor progress.
    """
    try:
        # Get current cluster
        cluster = await get_cnpg_cluster(namespace, name)

        # Update the instances count
        cluster['spec']['instances'] = instances

        # Apply the change
        custom_api, _ = get_kubernetes_clients()
        result = await asyncio.to_thread(
            custom_api.patch_namespaced_custom_object,
            group=CNPG_GROUP,
            version=CNPG_VERSION,
            namespace=namespace,
            plural=CNPG_PLURAL,
            name=name,
            body=cluster
        )
        
        return f"""Successfully initiated scaling of cluster '{namespace}/{name}' to {instances} instance(s).

The cluster will perform a rolling update to reach the desired instance count.
Monitor the scaling progress with:
get_cluster_status(namespace="{namespace}", name="{name}")
"""
    
    except Exception as e:
        return format_error_message(e, f"scaling cluster {namespace}/{name}")


# ============================================================================
# TODO: Additional tools to implement
# ============================================================================
# - delete_postgres_cluster: Delete a cluster
# - get_cluster_backups: List backups for a cluster
# - trigger_backup: Manually trigger a backup
# - restore_from_backup: Restore a cluster from backup
# - get_cluster_logs: Retrieve logs from cluster pods
# - execute_sql_query: Execute a SQL query (with safety guardrails)
# - create_database: Create a new database in a cluster
# - create_user: Create a new PostgreSQL user
# - get_connection_info: Get connection details for applications


# ============================================================================
# MCP Server Handlers
# ============================================================================

@mcp.list_tools()
async def list_tools() -> list[Tool]:
    """List all available MCP tools."""
    return [
        Tool(
            name="list_postgres_clusters",
            description="List all PostgreSQL clusters managed by CloudNativePG. Use this to discover available clusters, check their health status, and understand the current state of your PostgreSQL infrastructure.",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "Kubernetes namespace to list clusters from. If not provided, lists clusters from all namespaces."
                    },
                    "detail_level": {
                        "type": "string",
                        "enum": ["concise", "detailed"],
                        "description": "Level of detail in the response. Use 'concise' for a quick overview or 'detailed' for comprehensive information.",
                        "default": "concise"
                    }
                }
            }
        ),
        Tool(
            name="get_cluster_status",
            description="Get detailed status information for a specific PostgreSQL cluster. Use this to troubleshoot issues, verify cluster health, or get detailed insights into a specific cluster's operation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "Kubernetes namespace where the cluster exists."
                    },
                    "name": {
                        "type": "string",
                        "description": "Name of the CloudNativePG cluster."
                    },
                    "detail_level": {
                        "type": "string",
                        "enum": ["concise", "detailed"],
                        "description": "Level of detail. 'concise' provides essential status, 'detailed' includes conditions and full configuration.",
                        "default": "concise"
                    }
                },
                "required": ["namespace", "name"]
            }
        ),
        Tool(
            name="create_postgres_cluster",
            description="Create a new PostgreSQL cluster with CloudNativePG. This creates a high-availability PostgreSQL cluster with automatic replication, backups, and monitoring.",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "Kubernetes namespace where the cluster will be created. The namespace must exist."
                    },
                    "name": {
                        "type": "string",
                        "description": "Name for the new cluster. Must be a valid Kubernetes resource name (lowercase alphanumeric or '-').",
                        "pattern": "^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"
                    },
                    "instances": {
                        "type": "integer",
                        "description": "Number of PostgreSQL instances. Use 1 for development, 3+ for production HA.",
                        "default": 3,
                        "minimum": 1,
                        "maximum": 10
                    },
                    "storage_size": {
                        "type": "string",
                        "description": "Storage size per instance (e.g., '10Gi', '100Gi').",
                        "default": "10Gi"
                    },
                    "postgres_version": {
                        "type": "string",
                        "description": "PostgreSQL major version (e.g., '14', '15', '16').",
                        "default": "16"
                    },
                    "storage_class": {
                        "type": "string",
                        "description": "Kubernetes storage class. If not specified, uses the cluster default."
                    }
                },
                "required": ["namespace", "name"]
            }
        ),
        Tool(
            name="scale_postgres_cluster",
            description="Scale a PostgreSQL cluster by changing the number of instances. CloudNativePG handles the scaling process safely, ensuring data consistency.",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "Kubernetes namespace where the cluster exists."
                    },
                    "name": {
                        "type": "string",
                        "description": "Name of the cluster to scale."
                    },
                    "instances": {
                        "type": "integer",
                        "description": "New number of instances (1-10). For HA, use 3 or more.",
                        "minimum": 1,
                        "maximum": 10
                    }
                },
                "required": ["namespace", "name", "instances"]
            }
        )
    ]


@mcp.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool execution requests."""
    try:
        if name == "list_postgres_clusters":
            result = await list_postgres_clusters(
                namespace=arguments.get("namespace"),
                detail_level=arguments.get("detail_level", "concise")
            )
        elif name == "get_cluster_status":
            result = await get_cluster_status(
                namespace=arguments["namespace"],
                name=arguments["name"],
                detail_level=arguments.get("detail_level", "concise")
            )
        elif name == "create_postgres_cluster":
            result = await create_postgres_cluster(
                namespace=arguments["namespace"],
                name=arguments["name"],
                instances=arguments.get("instances", 3),
                storage_size=arguments.get("storage_size", "10Gi"),
                postgres_version=arguments.get("postgres_version", "16"),
                storage_class=arguments.get("storage_class")
            )
        elif name == "scale_postgres_cluster":
            result = await scale_postgres_cluster(
                namespace=arguments["namespace"],
                name=arguments["name"],
                instances=arguments["instances"]
            )
        else:
            raise ValueError(f"Unknown tool: {name}")

        return [TextContent(type="text", text=result)]

    except Exception as e:
        error_msg = format_error_message(e, f"executing tool '{name}'")
        return [TextContent(type="text", text=error_msg)]


@mcp.list_resources()
async def list_resources() -> list[Resource]:
    """List available resources (none for this server)."""
    return []


@mcp.read_resource()
async def read_resource(uri: str) -> str:
    """Read a resource by URI (not implemented)."""
    raise ValueError(f"Resource not found: {uri}")


@mcp.list_prompts()
async def list_prompts() -> list[Prompt]:
    """List available prompts (none for this server)."""
    return []


@mcp.get_prompt()
async def get_prompt(name: str, arguments: dict | None = None) -> str:
    """Get a prompt by name (not implemented)."""
    raise ValueError(f"Prompt not found: {name}")


# ============================================================================
# Transport Layer
# ============================================================================

async def run_stdio_transport():
    """
    Run the MCP server using stdio transport.

    This is the default mode for local usage with Claude Desktop.
    The server communicates via stdin/stdout and is managed as a child process.
    """
    from mcp.server.stdio import stdio_server

    print("Starting CloudNativePG MCP server with stdio transport...", file=sys.stderr)
    print(f"Python version: {sys.version}", file=sys.stderr)
    print(f"MCP server initialized with name: cloudnative-pg", file=sys.stderr)

    async with stdio_server() as (read_stream, write_stream):
        print("STDIO transport established, running server...", file=sys.stderr)
        await mcp.run(
            read_stream,
            write_stream,
            mcp.create_initialization_options()
        )
        print("Server run completed", file=sys.stderr)


async def run_http_transport(host: str = "0.0.0.0", port: int = 3000):
    """
    Run the MCP server using HTTP/SSE transport.
    
    This mode allows multiple clients to connect remotely and is suitable
    for team environments and production deployments.
    
    TODO: Implement HTTP transport when needed
    - Install: pip install mcp[sse] starlette uvicorn
    - Add SSE endpoints for event streaming
    - Add POST endpoint for client messages
    - Implement authentication/authorization
    - Add TLS support for production
    """
    raise NotImplementedError(
        "HTTP transport is not yet implemented. "
        "For now, use stdio transport (default mode).\n"
        "To add HTTP support, install: pip install mcp[sse] starlette uvicorn"
    )
    
    # Future implementation structure:
    # from mcp.server.sse import SseServerTransport
    # from starlette.applications import Starlette
    # from starlette.routing import Route
    # import uvicorn
    #
    # sse_transport = SseServerTransport("/messages")
    #
    # async def handle_sse(request):
    #     async with sse_transport.connect_sse(...) as streams:
    #         await mcp.run(streams[0], streams[1], ...)
    #
    # async def handle_messages(request):
    #     await sse_transport.handle_post_message(request)
    #
    # app = Starlette(routes=[
    #     Route("/sse", endpoint=handle_sse),
    #     Route("/messages", endpoint=handle_messages, methods=["POST"]),
    # ])
    #
    # uvicorn.run(app, host=host, port=port)


# ============================================================================
# Server Entry Point
# ============================================================================

def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="CloudNativePG MCP Server - Manage PostgreSQL clusters via MCP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with stdio transport (default, for Claude Desktop)
  python cnpg_mcp_server.py
  
  # Run with HTTP transport (future)
  python cnpg_mcp_server.py --transport http --port 3000
  
Environment Variables:
  KUBECONFIG        Path to kubernetes config file
  
For more information, see README.md
        """
    )
    
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode: 'stdio' for local use (default), 'http' for remote access"
    )
    
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (HTTP transport only, default: 0.0.0.0)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=3000,
        help="Port to listen on (HTTP transport only, default: 3000)"
    )
    
    return parser.parse_args()


async def main():
    """Main entry point - routes to appropriate transport."""
    args = parse_args()
    
    try:
        if args.transport == "stdio":
            await run_stdio_transport()
        elif args.transport == "http":
            await run_http_transport(host=args.host, port=args.port)
        else:
            print(f"Unknown transport mode: {args.transport}", file=sys.stderr)
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\nShutting down gracefully...", file=sys.stderr)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
