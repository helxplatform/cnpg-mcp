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
import secrets
import string
import base64
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


def get_current_namespace() -> str:
    """
    Get the current namespace from the Kubernetes context.

    Returns the namespace from the current context in kubeconfig, or 'default'
    if no namespace is specified in the context or if in-cluster config is used.
    """
    try:
        # Try to get the current context from kubeconfig
        contexts, active_context = config.list_kube_config_contexts()
        if active_context and 'namespace' in active_context.get('context', {}):
            namespace = active_context['context']['namespace']
            print(f"Using namespace from context: {namespace}", file=sys.stderr)
            return namespace
    except Exception as e:
        # If we can't get the context (e.g., in-cluster config), fall back to default
        print(f"Could not get namespace from context: {e}, using 'default'", file=sys.stderr)

    return "default"


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
        try:
            body = json.loads(error.body) if error.body else {}
            message = body.get('message', str(error))
        except (json.JSONDecodeError, ValueError) as json_error:
            # If the error body isn't valid JSON, use the raw body or string representation
            message = error.body if error.body else str(error)
        
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


def generate_password(length: int = 16) -> str:
    """Generate a random alphanumeric password."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


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
    name: str = Field(
        ...,
        description="Name of the CloudNativePG cluster.",
        examples=["my-postgres-cluster", "production-db"]
    )
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context.",
        examples=["default", "production", "postgres-system"]
    )
    detail_level: Literal["concise", "detailed"] = Field(
        "concise",
        description="Level of detail in the response."
    )


class CreateClusterInput(BaseModel):
    """Input for creating a new PostgreSQL cluster."""
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
    wait: bool = Field(
        False,
        description="Wait for the cluster to become operational before returning. If False, returns immediately after creation. Automatically set to False if instances > 5."
    )
    timeout: Optional[int] = Field(
        None,
        description="Maximum time in seconds to wait for cluster to become operational (only used if wait=True). If not specified, defaults to 60 seconds per instance. Must be between 30 and 600 seconds.",
        ge=30,
        le=600
    )
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace where the cluster will be created. If not specified, uses the current namespace from your Kubernetes context.",
        examples=["default", "production"]
    )


class ScaleClusterInput(BaseModel):
    """Input for scaling a cluster."""
    name: str = Field(..., description="Name of the cluster to scale.")
    instances: int = Field(
        ...,
        description="New number of instances.",
        ge=1,
        le=10
    )
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace of the cluster. If not specified, uses the current namespace from your Kubernetes context."
    )


class DeleteClusterInput(BaseModel):
    """Input for deleting a cluster."""
    name: str = Field(
        ...,
        description="Name of the cluster to delete.",
        examples=["my-postgres-cluster", "old-test-cluster"]
    )
    confirm_deletion: bool = Field(
        False,
        description="Must be explicitly set to true to confirm deletion. This is a safety mechanism to prevent accidental deletion of clusters."
    )
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
    )


class ListRolesInput(BaseModel):
    """Input for listing PostgreSQL roles."""
    cluster_name: str = Field(..., description="Name of the PostgreSQL cluster.")
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
    )


class CreateRoleInput(BaseModel):
    """Input for creating a PostgreSQL role."""
    cluster_name: str = Field(..., description="Name of the PostgreSQL cluster.")
    role_name: str = Field(
        ...,
        description="Name of the role to create.",
        pattern=r'^[a-z_][a-z0-9_]*$'
    )
    login: bool = Field(True, description="Allow role to log in. Default: true.")
    superuser: bool = Field(False, description="Grant superuser privileges. Default: false.")
    inherit: bool = Field(True, description="Inherit privileges from roles it is a member of. Default: true.")
    createdb: bool = Field(False, description="Allow role to create databases. Default: false.")
    createrole: bool = Field(False, description="Allow role to create other roles. Default: false.")
    replication: bool = Field(False, description="Allow role to initiate streaming replication. Default: false.")
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
    )


class UpdateRoleInput(BaseModel):
    """Input for updating a PostgreSQL role."""
    cluster_name: str = Field(..., description="Name of the PostgreSQL cluster.")
    role_name: str = Field(..., description="Name of the role to update.")
    login: Optional[bool] = Field(None, description="Allow role to log in.")
    superuser: Optional[bool] = Field(None, description="Grant superuser privileges.")
    inherit: Optional[bool] = Field(None, description="Inherit privileges from roles it is a member of.")
    createdb: Optional[bool] = Field(None, description="Allow role to create databases.")
    createrole: Optional[bool] = Field(None, description="Allow role to create other roles.")
    replication: Optional[bool] = Field(None, description="Allow role to initiate streaming replication.")
    password: Optional[str] = Field(None, description="New password for the role. If not specified, password remains unchanged.")
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
    )


class DeleteRoleInput(BaseModel):
    """Input for deleting a PostgreSQL role."""
    cluster_name: str = Field(..., description="Name of the PostgreSQL cluster.")
    role_name: str = Field(..., description="Name of the role to delete.")
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
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
    name: str,
    namespace: Optional[str] = None,
    detail_level: Literal["concise", "detailed"] = "concise"
) -> str:
    """
    Get detailed status information for a specific PostgreSQL cluster.

    This tool retrieves comprehensive information about a CloudNativePG cluster,
    including its current state, health conditions, replica status, and configuration.
    Use this to troubleshoot issues, verify cluster health, or get detailed insights
    into a specific cluster's operation.

    Args:
        name: Name of the CloudNativePG cluster resource.
        namespace: Kubernetes namespace where the cluster exists. If not specified,
                  uses the current namespace from your Kubernetes context. Cluster
                  names are only unique within a namespace.
        detail_level: Level of detail. 'concise' provides essential status information,
                     'detailed' includes conditions, events, resource usage, and full
                     configuration.

    Returns:
        Formatted string with cluster status information including phase, ready instances,
        primary pod, PostgreSQL version, storage configuration, and detailed conditions
        if requested.

    Examples:
        - get_cluster_status(name="main-db")  # Uses current context namespace
        - get_cluster_status(name="main-db", namespace="production")
        - get_cluster_status(name="test-db", detail_level="detailed")

    Error Handling:
        - Returns 404 if cluster doesn't exist: Double-check the namespace and name.
        - Returns 403 if permissions are insufficient: Verify RBAC permissions for the
          postgresql.cnpg.io/clusters resource.
    """
    try:
        # Infer namespace from context if not provided
        if namespace is None:
            namespace = get_current_namespace()

        cluster = await get_cnpg_cluster(namespace, name)
        result = format_cluster_status(cluster, detail_level)
        return truncate_response(result)

    except Exception as e:
        return format_error_message(e, f"getting cluster status for {namespace}/{name}")


async def create_postgres_cluster(
    name: str,
    instances: int = 3,
    storage_size: str = "10Gi",
    postgres_version: str = "16",
    storage_class: Optional[str] = None,
    wait: bool = False,
    timeout: Optional[int] = None,
    namespace: Optional[str] = None
) -> str:
    """
    Create a new PostgreSQL cluster with CloudNativePG.

    This tool creates a new high-availability PostgreSQL cluster with the specified
    configuration. The cluster will automatically set up replication, backups, and
    monitoring. This is a comprehensive workflow tool that handles the entire cluster
    creation process.

    Args:
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
        wait: If True, wait for the cluster to become operational before returning.
              If False (default), return immediately after creation. Automatically
              set to False if instances > 5 (to avoid waiting more than 5 minutes).
        timeout: Maximum time in seconds to wait for cluster to become operational
                (only used if wait=True). If not specified, defaults to 60 seconds
                per instance. Range: 30-600 seconds (0.5-10 minutes).
        namespace: Kubernetes namespace where the cluster will be created. If not specified,
                  uses the current namespace from your Kubernetes context. The namespace
                  must exist before creating the cluster.

    Returns:
        Success message with cluster details if creation succeeds, or detailed error
        message with suggestions if it fails. If wait=True, includes final cluster status.

    Examples:
        - Simple cluster: create_postgres_cluster(name="my-db")
        - Wait for ready (auto-timeout 3min for 3 instances): create_postgres_cluster(name="my-db", wait=True)
        - With custom timeout: create_postgres_cluster(name="my-db", wait=True, timeout=300)
        - Large cluster (wait auto-disabled): create_postgres_cluster(name="big-db", instances=8, wait=True)
        - Production cluster: create_postgres_cluster(
            name="main-db",
            instances=5,
            storage_size="100Gi",
            postgres_version="16",
            storage_class="fast-ssd",
            wait=True,
            namespace="production"
          )

    Error Handling:
        - 409 Conflict: Cluster with this name already exists. Choose a different name
          or delete the existing cluster first.
        - 422 Invalid: Check that all parameters meet CloudNativePG requirements.
        - 403 Forbidden: Ensure service account has 'create' permission for
          postgresql.cnpg.io/clusters.
        - Timeout: If wait=True and cluster doesn't become ready within timeout period.

    Note:
        Cluster creation is asynchronous. If wait=False, use get_cluster_status() to
        monitor the cluster until it reaches 'Cluster in healthy state' phase.
    """
    try:
        # Infer namespace from context if not provided
        if namespace is None:
            namespace = get_current_namespace()

        # Auto-disable wait for large clusters (> 5 instances)
        # Waiting more than 5 minutes is too long
        original_wait = wait
        if instances > 5:
            wait = False

        # Calculate dynamic timeout based on instances if not provided
        # Default: 60 seconds per instance
        if timeout is None:
            timeout = instances * 60
        # Clamp timeout to valid range (30-600 seconds)
        timeout = max(30, min(600, timeout))

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

        # If wait is False, return immediately
        if not wait:
            auto_disabled_msg = ""
            if original_wait and instances > 5:
                auto_disabled_msg = f"\n⏭️  Note: Wait was automatically disabled because {instances} instances would require waiting up to {instances * 60} seconds (more than 5 minutes).\n"

            return f"""Successfully created PostgreSQL cluster '{cluster_name}' in namespace '{namespace}'.

Configuration:
- Instances: {instances}
- PostgreSQL Version: {postgres_version}
- Storage Size: {storage_size}
{f'- Storage Class: {storage_class}' if storage_class else ''}{auto_disabled_msg}
The cluster is now being provisioned. You can monitor its status using:
get_cluster_status(namespace="{namespace}", name="{cluster_name}")

Wait until the cluster reaches 'Cluster in healthy state' phase before connecting.
"""

        # Wait for cluster to become operational
        import time
        start_time = time.time()
        poll_interval = 5  # Check every 5 seconds

        while True:
            elapsed = time.time() - start_time

            # Check timeout
            if elapsed >= timeout:
                return f"""Cluster '{cluster_name}' created but TIMED OUT waiting for it to become operational.

Configuration:
- Instances: {instances}
- PostgreSQL Version: {postgres_version}
- Storage Size: {storage_size}
{f'- Storage Class: {storage_class}' if storage_class else ''}

Timeout: {timeout} seconds elapsed

The cluster is still provisioning. Check status with:
get_cluster_status(namespace="{namespace}", name="{cluster_name}")

Note: Cluster creation can take several minutes depending on storage provisioning
and PostgreSQL initialization time.
"""

            # Get current cluster status
            try:
                cluster = await get_cnpg_cluster(namespace, cluster_name)
                status = cluster.get('status', {})
                phase = status.get('phase', '')
                ready_instances = status.get('readyInstances', 0)

                # Check if cluster is healthy
                if 'healthy' in phase.lower() and ready_instances == instances:
                    current_primary = status.get('currentPrimary', 'unknown')
                    return f"""Successfully created PostgreSQL cluster '{cluster_name}' in namespace '{namespace}'.

Configuration:
- Instances: {instances} ({ready_instances} ready)
- PostgreSQL Version: {postgres_version}
- Storage Size: {storage_size}
{f'- Storage Class: {storage_class}' if storage_class else ''}
- Current Primary: {current_primary}

Status: {phase}

✅ Cluster is operational and ready for connections!

Time elapsed: {int(elapsed)} seconds

Get connection details with:
kubectl get secret {cluster_name}-app -n {namespace} -o jsonpath='{{.data.password}}' | base64 -d
"""

            except Exception:
                # Cluster might not be fully created yet, continue waiting
                pass

            # Wait before next check
            await asyncio.sleep(poll_interval)

    except Exception as e:
        return format_error_message(e, f"creating cluster {namespace}/{name}")


async def scale_postgres_cluster(
    name: str,
    instances: int,
    namespace: Optional[str] = None
) -> str:
    """
    Scale a PostgreSQL cluster by changing the number of instances.

    This tool modifies the number of PostgreSQL instances in a cluster, allowing you
    to scale up for increased capacity or scale down to reduce resource usage.
    CloudNativePG handles the scaling process safely, ensuring data consistency.

    Args:
        name: Name of the cluster to scale.
        instances: New number of instances (1-10). For high availability, use 3 or more.
        namespace: Kubernetes namespace where the cluster exists. If not specified,
                  uses the current namespace from your Kubernetes context.

    Returns:
        Success message if the scaling operation is initiated, or error details if it fails.

    Examples:
        - Scale up: scale_postgres_cluster(name="main-db", instances=5)
        - Scale with namespace: scale_postgres_cluster(name="main-db", instances=5, namespace="production")
        - Scale down: scale_postgres_cluster(name="test-db", instances=1)

    Error Handling:
        - 404: Cluster not found. Verify namespace and name.
        - 422: Invalid instance count. Must be between 1 and 10.
        - Scaling is performed as a rolling update. Monitor with get_cluster_status().

    Note:
        Scaling is asynchronous. The cluster will gradually adjust to the new size.
        Use get_cluster_status() to monitor progress.
    """
    try:
        # Infer namespace from context if not provided
        if namespace is None:
            namespace = get_current_namespace()

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


async def delete_postgres_cluster(
    name: str,
    confirm_deletion: bool = False,
    namespace: Optional[str] = None
) -> str:
    """
    Delete a PostgreSQL cluster and its associated resources.

    This tool permanently deletes a CloudNativePG cluster. This is a destructive
    operation that cannot be undone. All data will be lost unless you have backups.
    Use with caution, especially in production environments.

    Args:
        name: Name of the cluster to delete.
        confirm_deletion: Must be explicitly set to True to confirm deletion.
                         This is a required safety mechanism to prevent accidental deletions.
        namespace: Kubernetes namespace where the cluster exists. If not specified,
                  uses the current namespace from your Kubernetes context.

    Returns:
        Success message if deletion is initiated, warning message if not confirmed,
        or error details if it fails.

    Examples:
        - Request deletion (shows warning): delete_postgres_cluster(name="old-test-cluster")
        - Confirm deletion: delete_postgres_cluster(name="old-test-cluster", confirm_deletion=True)

    Error Handling:
        - 404: Cluster not found. Verify namespace and name.
        - 403: Permission denied. Ensure service account has 'delete' permission.

    Warning:
        This operation is DESTRUCTIVE and IRREVERSIBLE. All data in the cluster
        will be permanently lost. Make sure you have backups before deleting
        production clusters. The persistent volumes may be retained or deleted
        depending on the storage class reclaim policy.
    """
    try:
        # Infer namespace from context if not provided
        if namespace is None:
            namespace = get_current_namespace()

        # Check if deletion is confirmed
        if not confirm_deletion:
            # Verify cluster exists to provide accurate warning
            await get_cnpg_cluster(namespace, name)

            return f"""⚠️  DELETION NOT CONFIRMED

You are about to delete the PostgreSQL cluster '{namespace}/{name}'.

⚠️  WARNING: This is a DESTRUCTIVE and IRREVERSIBLE operation:
- All data in this cluster will be PERMANENTLY LOST
- All databases, tables, and data will be deleted
- Depending on storage class policy, persistent volumes may be deleted
- This action CANNOT be undone

Before proceeding, ensure you have:
✓ Backed up all important data
✓ Verified this is the correct cluster to delete
✓ Confirmed with your team (if applicable)

To proceed with deletion, call this tool again with confirm_deletion=True:

delete_postgres_cluster(
    name="{name}",
    namespace="{namespace}",
    confirm_deletion=True
)

To cancel, simply do not call the tool again.
"""

        # Verify cluster exists before attempting deletion
        await get_cnpg_cluster(namespace, name)

        # Delete the cluster
        custom_api, _ = get_kubernetes_clients()
        await asyncio.to_thread(
            custom_api.delete_namespaced_custom_object,
            group=CNPG_GROUP,
            version=CNPG_VERSION,
            namespace=namespace,
            plural=CNPG_PLURAL,
            name=name
        )

        return f"""Successfully initiated deletion of cluster '{namespace}/{name}'.

⚠️  WARNING: This is a destructive operation. All data in this cluster will be permanently lost.

The cluster and its pods are being terminated. Depending on your storage class
reclaim policy, the persistent volumes may be:
- Retained: PVCs remain and can be manually deleted later
- Deleted: PVCs are automatically deleted (data loss is permanent)

Check deletion progress with:
kubectl get cluster {name} -n {namespace}

The cluster will no longer appear in list_postgres_clusters() once deletion is complete.
"""

    except Exception as e:
        return format_error_message(e, f"deleting cluster {namespace}/{name}")


async def list_postgres_roles(
    cluster_name: str,
    namespace: Optional[str] = None
) -> str:
    """
    List all PostgreSQL roles/users managed in a cluster.

    Reads roles from the Cluster CRD's .spec.managed.roles field.

    Args:
        cluster_name: Name of the PostgreSQL cluster.
        namespace: Kubernetes namespace where the cluster exists.

    Returns:
        Formatted list of roles with their attributes.
    """
    try:
        if namespace is None:
            namespace = get_current_namespace()

        # Get the cluster to read managed roles
        cluster = await get_cnpg_cluster(namespace, cluster_name)
        managed_roles = cluster.get('spec', {}).get('managed', {}).get('roles', [])

        if not managed_roles:
            return f"No managed roles defined in cluster '{namespace}/{cluster_name}'.\n\nRoles are managed through the Cluster CRD's .spec.managed.roles field."

        result = f"PostgreSQL Roles managed in cluster '{namespace}/{cluster_name}':\n\n"

        for role in managed_roles:
            name = role.get('name', 'unknown')
            ensure = role.get('ensure', 'present')
            login = role.get('login', False)
            superuser = role.get('superuser', False)
            inherit = role.get('inherit', True)
            createdb = role.get('createdb', False)
            createrole = role.get('createrole', False)
            replication = role.get('replication', False)
            password_secret = role.get('passwordSecret', {}).get('name', 'none')
            in_roles = role.get('inRoles', [])

            result += f"**{name}**\n"
            result += f"  - Ensure: {ensure}\n"
            result += f"  - Login: {login}\n"
            result += f"  - Superuser: {superuser}\n"
            result += f"  - Inherit: {inherit}\n"
            result += f"  - Create DB: {createdb}\n"
            result += f"  - Create Role: {createrole}\n"
            result += f"  - Replication: {replication}\n"
            result += f"  - Password Secret: {password_secret}\n"
            if in_roles:
                result += f"  - Member of: {', '.join(in_roles)}\n"
            result += "\n"

        return result

    except Exception as e:
        return format_error_message(e, f"listing roles in cluster {namespace}/{cluster_name}")


async def create_postgres_role(
    cluster_name: str,
    role_name: str,
    login: bool = True,
    superuser: bool = False,
    inherit: bool = True,
    createdb: bool = False,
    createrole: bool = False,
    replication: bool = False,
    namespace: Optional[str] = None
) -> str:
    """
    Create a new PostgreSQL role/user in a cluster using CloudNativePG's declarative role management.

    Automatically generates a secure password and stores it in a Kubernetes secret.
    Adds the role to the Cluster CRD's .spec.managed.roles field.

    Args:
        cluster_name: Name of the PostgreSQL cluster.
        role_name: Name of the role to create.
        login: Allow role to log in (default: true).
        superuser: Grant superuser privileges (default: false).
        inherit: Inherit privileges from parent roles (default: true).
        createdb: Allow creating databases (default: false).
        createrole: Allow creating roles (default: false).
        replication: Allow streaming replication (default: false).
        namespace: Kubernetes namespace.

    Returns:
        Success message with password retrieval instructions.
    """
    try:
        if namespace is None:
            namespace = get_current_namespace()

        # Generate a secure password
        password = generate_password(16)

        # Create Kubernetes secret to store the password
        secret_name = f"{cluster_name}-user-{role_name}"
        _, core_api = get_kubernetes_clients()

        secret_data = {
            "username": base64.b64encode(role_name.encode()).decode(),
            "password": base64.b64encode(password.encode()).decode()
        }

        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(
                name=secret_name,
                namespace=namespace,
                labels={
                    "app.kubernetes.io/name": "cnpg",
                    "cnpg.io/cluster": cluster_name,
                    "cnpg.io/role": role_name
                }
            ),
            data=secret_data,
            type="kubernetes.io/basic-auth"
        )

        await asyncio.to_thread(
            core_api.create_namespaced_secret,
            namespace=namespace,
            body=secret
        )

        # Get the cluster and add the role to .spec.managed.roles
        cluster = await get_cnpg_cluster(namespace, cluster_name)

        # Ensure managed.roles exists
        if 'managed' not in cluster['spec']:
            cluster['spec']['managed'] = {}
        if 'roles' not in cluster['spec']['managed']:
            cluster['spec']['managed']['roles'] = []

        # Check if role already exists
        existing_role = next((r for r in cluster['spec']['managed']['roles'] if r.get('name') == role_name), None)
        if existing_role:
            return f"Error: Role '{role_name}' already exists in cluster '{namespace}/{cluster_name}'."

        # Add the new role
        new_role = {
            "name": role_name,
            "ensure": "present",
            "login": login,
            "superuser": superuser,
            "inherit": inherit,
            "createdb": createdb,
            "createrole": createrole,
            "replication": replication,
            "passwordSecret": {
                "name": secret_name
            }
        }

        cluster['spec']['managed']['roles'].append(new_role)

        # Update the cluster
        custom_api, _ = get_kubernetes_clients()
        await asyncio.to_thread(
            custom_api.patch_namespaced_custom_object,
            group=CNPG_GROUP,
            version=CNPG_VERSION,
            namespace=namespace,
            plural=CNPG_PLURAL,
            name=cluster_name,
            body=cluster
        )

        return f"""Successfully created PostgreSQL role '{role_name}' in cluster '{namespace}/{cluster_name}'.

Role Attributes:
- Login: {login}
- Superuser: {superuser}
- Inherit: {inherit}
- Create DB: {createdb}
- Create Role: {createrole}
- Replication: {replication}

Password stored in Kubernetes secret: {secret_name}

To retrieve the password:
kubectl get secret {secret_name} -n {namespace} -o jsonpath='{{.data.password}}' | base64 -d

Connection string:
postgresql://{role_name}:<password>@{cluster_name}-rw.{namespace}.svc:5432/app

The CloudNativePG operator will reconcile this role in the database.
"""

    except Exception as e:
        return format_error_message(e, f"creating role {role_name} in cluster {namespace}/{cluster_name}")


async def update_postgres_role(
    cluster_name: str,
    role_name: str,
    login: Optional[bool] = None,
    superuser: Optional[bool] = None,
    inherit: Optional[bool] = None,
    createdb: Optional[bool] = None,
    createrole: Optional[bool] = None,
    replication: Optional[bool] = None,
    password: Optional[str] = None,
    namespace: Optional[str] = None
) -> str:
    """
    Update attributes of an existing PostgreSQL role using CloudNativePG's declarative role management.

    Args:
        cluster_name: Name of the PostgreSQL cluster.
        role_name: Name of the role to update.
        login, superuser, inherit, createdb, createrole, replication: Optional attribute changes.
        password: Optional new password. If not provided, password remains unchanged.
        namespace: Kubernetes namespace.

    Returns:
        Success message with updated attributes.
    """
    try:
        if namespace is None:
            namespace = get_current_namespace()

        # Get the cluster
        cluster = await get_cnpg_cluster(namespace, cluster_name)
        managed_roles = cluster.get('spec', {}).get('managed', {}).get('roles', [])

        # Find the role
        role = next((r for r in managed_roles if r.get('name') == role_name), None)
        if not role:
            return f"Error: Role '{role_name}' not found in cluster '{namespace}/{cluster_name}'."

        updates = []

        # Update attributes
        if login is not None:
            role['login'] = login
            updates.append(f"Login: {login}")

        if superuser is not None:
            role['superuser'] = superuser
            updates.append(f"Superuser: {superuser}")

        if inherit is not None:
            role['inherit'] = inherit
            updates.append(f"Inherit: {inherit}")

        if createdb is not None:
            role['createdb'] = createdb
            updates.append(f"Create DB: {createdb}")

        if createrole is not None:
            role['createrole'] = createrole
            updates.append(f"Create Role: {createrole}")

        if replication is not None:
            role['replication'] = replication
            updates.append(f"Replication: {replication}")

        if password is not None:
            # Update the secret
            secret_name = f"{cluster_name}-user-{role_name}"
            _, core_api = get_kubernetes_clients()

            try:
                secret = await asyncio.to_thread(
                    core_api.read_namespaced_secret,
                    name=secret_name,
                    namespace=namespace
                )
                secret.data["password"] = base64.b64encode(password.encode()).decode()
                await asyncio.to_thread(
                    core_api.replace_namespaced_secret,
                    name=secret_name,
                    namespace=namespace,
                    body=secret
                )
                updates.append("Password: updated")
            except ApiException as e:
                return f"Error: Secret '{secret_name}' not found. Cannot update password."

        if not updates:
            return "No updates specified. Please provide at least one attribute to update."

        # Update the cluster
        custom_api, _ = get_kubernetes_clients()
        await asyncio.to_thread(
            custom_api.patch_namespaced_custom_object,
            group=CNPG_GROUP,
            version=CNPG_VERSION,
            namespace=namespace,
            plural=CNPG_PLURAL,
            name=cluster_name,
            body=cluster
        )

        updates_text = '\n- '.join(updates)
        return f"""Successfully updated PostgreSQL role '{role_name}' in cluster '{namespace}/{cluster_name}'.

Updated Attributes:
- {updates_text}

The CloudNativePG operator will reconcile these changes in the database.
"""

    except Exception as e:
        return format_error_message(e, f"updating role {role_name} in cluster {namespace}/{cluster_name}")


async def delete_postgres_role(
    cluster_name: str,
    role_name: str,
    namespace: Optional[str] = None
) -> str:
    """
    Delete a PostgreSQL role from a cluster using CloudNativePG's declarative role management.

    Sets the role's ensure field to 'absent' or removes it from .spec.managed.roles.
    Also deletes the associated Kubernetes secret.

    Args:
        cluster_name: Name of the PostgreSQL cluster.
        role_name: Name of the role to delete.
        namespace: Kubernetes namespace.

    Returns:
        Success message.
    """
    try:
        if namespace is None:
            namespace = get_current_namespace()

        # Get the cluster
        cluster = await get_cnpg_cluster(namespace, cluster_name)
        managed_roles = cluster.get('spec', {}).get('managed', {}).get('roles', [])

        # Find and remove the role
        role_index = next((i for i, r in enumerate(managed_roles) if r.get('name') == role_name), None)
        if role_index is None:
            return f"Error: Role '{role_name}' not found in cluster '{namespace}/{cluster_name}'."

        # Remove the role from the list
        managed_roles.pop(role_index)

        # Update the cluster
        custom_api, _ = get_kubernetes_clients()
        await asyncio.to_thread(
            custom_api.patch_namespaced_custom_object,
            group=CNPG_GROUP,
            version=CNPG_VERSION,
            namespace=namespace,
            plural=CNPG_PLURAL,
            name=cluster_name,
            body=cluster
        )

        # Delete the associated secret
        secret_name = f"{cluster_name}-user-{role_name}"
        _, core_api = get_kubernetes_clients()

        try:
            await asyncio.to_thread(
                core_api.delete_namespaced_secret,
                name=secret_name,
                namespace=namespace
            )
            secret_deleted = True
        except ApiException:
            # Secret doesn't exist or already deleted
            secret_deleted = False

        secret_msg = f"\nAssociated secret '{secret_name}' was also deleted." if secret_deleted else ""

        return f"""Successfully deleted PostgreSQL role '{role_name}' from cluster '{namespace}/{cluster_name}'.{secret_msg}

The CloudNativePG operator will drop this role from the database.
"""

    except Exception as e:
        return format_error_message(e, f"deleting role {role_name} from cluster {namespace}/{cluster_name}")


# ============================================================================
# TODO: Additional tools to implement
# ============================================================================
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
                    "name": {
                        "type": "string",
                        "description": "Name of the CloudNativePG cluster."
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
                    },
                    "detail_level": {
                        "type": "string",
                        "enum": ["concise", "detailed"],
                        "description": "Level of detail. 'concise' provides essential status, 'detailed' includes conditions and full configuration.",
                        "default": "concise"
                    }
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="create_postgres_cluster",
            description="Create a new PostgreSQL cluster with CloudNativePG. This creates a high-availability PostgreSQL cluster with automatic replication, backups, and monitoring.",
            inputSchema={
                "type": "object",
                "properties": {
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
                    },
                    "wait": {
                        "type": "boolean",
                        "description": "Wait for the cluster to become operational before returning. If false (default), returns immediately after creation. Automatically set to false if instances > 5 to avoid waiting more than 5 minutes.",
                        "default": False
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Maximum time in seconds to wait for cluster to become operational (only used if wait=true). If not specified, defaults to 60 seconds per instance. Must be between 30 and 600 seconds.",
                        "minimum": 30,
                        "maximum": 600
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Kubernetes namespace where the cluster will be created. If not specified, uses the current namespace from your Kubernetes context. The namespace must exist."
                    }
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="scale_postgres_cluster",
            description="Scale a PostgreSQL cluster by changing the number of instances. CloudNativePG handles the scaling process safely, ensuring data consistency.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the cluster to scale."
                    },
                    "instances": {
                        "type": "integer",
                        "description": "New number of instances (1-10). For HA, use 3 or more.",
                        "default": 3,
                        "minimum": 1,
                        "maximum": 10
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
                    }
                },
                "required": ["name", "instances"]
            }
        ),
        Tool(
            name="delete_postgres_cluster",
            description="Delete a PostgreSQL cluster and its associated resources. This is a DESTRUCTIVE operation that permanently removes the cluster and all its data. Requires explicit confirmation to proceed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the cluster to delete."
                    },
                    "confirm_deletion": {
                        "type": "boolean",
                        "description": "Must be explicitly set to true to confirm deletion. If false or omitted, returns a warning message without deleting.",
                        "default": False
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
                    }
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="list_postgres_roles",
            description="List all PostgreSQL roles/users in a cluster. Shows role attributes like login, superuser, createdb, etc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cluster_name": {
                        "type": "string",
                        "description": "Name of the PostgreSQL cluster."
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
                    }
                },
                "required": ["cluster_name"]
            }
        ),
        Tool(
            name="create_postgres_role",
            description="Create a new PostgreSQL role/user in a cluster. Automatically generates a secure password and stores it in a Kubernetes secret.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cluster_name": {
                        "type": "string",
                        "description": "Name of the PostgreSQL cluster."
                    },
                    "role_name": {
                        "type": "string",
                        "description": "Name of the role to create. Must start with a letter or underscore, followed by letters, numbers, or underscores.",
                        "pattern": "^[a-z_][a-z0-9_]*$"
                    },
                    "login": {
                        "type": "boolean",
                        "description": "Allow role to log in.",
                        "default": True
                    },
                    "superuser": {
                        "type": "boolean",
                        "description": "Grant superuser privileges.",
                        "default": False
                    },
                    "inherit": {
                        "type": "boolean",
                        "description": "Inherit privileges from roles it is a member of.",
                        "default": True
                    },
                    "createdb": {
                        "type": "boolean",
                        "description": "Allow role to create databases.",
                        "default": False
                    },
                    "createrole": {
                        "type": "boolean",
                        "description": "Allow role to create other roles.",
                        "default": False
                    },
                    "replication": {
                        "type": "boolean",
                        "description": "Allow role to initiate streaming replication.",
                        "default": False
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
                    }
                },
                "required": ["cluster_name", "role_name"]
            }
        ),
        Tool(
            name="update_postgres_role",
            description="Update attributes of an existing PostgreSQL role/user. Can modify permissions and password.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cluster_name": {
                        "type": "string",
                        "description": "Name of the PostgreSQL cluster."
                    },
                    "role_name": {
                        "type": "string",
                        "description": "Name of the role to update."
                    },
                    "login": {
                        "type": "boolean",
                        "description": "Allow role to log in."
                    },
                    "superuser": {
                        "type": "boolean",
                        "description": "Grant superuser privileges."
                    },
                    "inherit": {
                        "type": "boolean",
                        "description": "Inherit privileges from roles it is a member of."
                    },
                    "createdb": {
                        "type": "boolean",
                        "description": "Allow role to create databases."
                    },
                    "createrole": {
                        "type": "boolean",
                        "description": "Allow role to create other roles."
                    },
                    "replication": {
                        "type": "boolean",
                        "description": "Allow role to initiate streaming replication."
                    },
                    "password": {
                        "type": "string",
                        "description": "New password for the role. If not specified, password remains unchanged."
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
                    }
                },
                "required": ["cluster_name", "role_name"]
            }
        ),
        Tool(
            name="delete_postgres_role",
            description="Delete a PostgreSQL role/user from a cluster. Also deletes the associated Kubernetes secret containing the password.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cluster_name": {
                        "type": "string",
                        "description": "Name of the PostgreSQL cluster."
                    },
                    "role_name": {
                        "type": "string",
                        "description": "Name of the role to delete."
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
                    }
                },
                "required": ["cluster_name", "role_name"]
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
                name=arguments["name"],
                namespace=arguments.get("namespace"),
                detail_level=arguments.get("detail_level", "concise")
            )
        elif name == "create_postgres_cluster":
            result = await create_postgres_cluster(
                name=arguments["name"],
                instances=arguments.get("instances", 3),
                storage_size=arguments.get("storage_size", "10Gi"),
                postgres_version=arguments.get("postgres_version", "16"),
                storage_class=arguments.get("storage_class"),
                wait=arguments.get("wait", False),
                timeout=arguments.get("timeout"),  # None triggers dynamic calculation
                namespace=arguments.get("namespace")
            )
        elif name == "scale_postgres_cluster":
            result = await scale_postgres_cluster(
                name=arguments["name"],
                instances=arguments["instances"],
                namespace=arguments.get("namespace")
            )
        elif name == "delete_postgres_cluster":
            result = await delete_postgres_cluster(
                name=arguments["name"],
                confirm_deletion=arguments.get("confirm_deletion", False),
                namespace=arguments.get("namespace")
            )
        elif name == "list_postgres_roles":
            result = await list_postgres_roles(
                cluster_name=arguments["cluster_name"],
                namespace=arguments.get("namespace")
            )
        elif name == "create_postgres_role":
            result = await create_postgres_role(
                cluster_name=arguments["cluster_name"],
                role_name=arguments["role_name"],
                login=arguments.get("login", True),
                superuser=arguments.get("superuser", False),
                inherit=arguments.get("inherit", True),
                createdb=arguments.get("createdb", False),
                createrole=arguments.get("createrole", False),
                replication=arguments.get("replication", False),
                namespace=arguments.get("namespace")
            )
        elif name == "update_postgres_role":
            result = await update_postgres_role(
                cluster_name=arguments["cluster_name"],
                role_name=arguments["role_name"],
                login=arguments.get("login"),
                superuser=arguments.get("superuser"),
                inherit=arguments.get("inherit"),
                createdb=arguments.get("createdb"),
                createrole=arguments.get("createrole"),
                replication=arguments.get("replication"),
                password=arguments.get("password"),
                namespace=arguments.get("namespace")
            )
        elif name == "delete_postgres_role":
            result = await delete_postgres_role(
                cluster_name=arguments["cluster_name"],
                role_name=arguments["role_name"],
                namespace=arguments.get("namespace")
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
