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
import os
import argparse
import secrets
import string
import base64
import yaml
from typing import Any, Dict, List, Optional, Literal
from datetime import datetime

from fastmcp import FastMCP
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
CNPG_DATABASE_PLURAL = "databases"

# Transport mode (set via CLI args)
TRANSPORT_MODE = "stdio"  # or "http"

# ============================================================================
# Server Initialization
# ============================================================================

# Initialize FastMCP server
mcp = FastMCP("cloudnative-pg")

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

        # Default to current namespace if not specified (consistent with other tools)
        if namespace is None:
            namespace = get_current_namespace()

        result = await asyncio.to_thread(
            custom_api.list_namespaced_custom_object,
            group=CNPG_GROUP,
            version=CNPG_VERSION,
            namespace=namespace,
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
        description="Kubernetes namespace to list clusters from. If not provided, uses the current namespace from your Kubernetes context."
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
    dry_run: bool = Field(
        False,
        description="If True, returns the cluster definition without creating it. Useful for previewing the configuration before applying it."
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
    dry_run: bool = Field(
        False,
        description="If True, shows what would be changed without applying it. Useful for previewing the scaling operation."
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
    dry_run: bool = Field(
        False,
        description="If True, shows what would be deleted without performing the deletion. Useful for previewing the deletion impact."
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
    dry_run: bool = Field(
        False,
        description="If True, shows the role definition that would be created without creating it. Useful for previewing the configuration."
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
    dry_run: bool = Field(
        False,
        description="If True, shows what changes would be made without applying them. Useful for previewing the update."
    )


class DeleteRoleInput(BaseModel):
    """Input for deleting a PostgreSQL role."""
    cluster_name: str = Field(..., description="Name of the PostgreSQL cluster.")
    role_name: str = Field(..., description="Name of the role to delete.")
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
    )
    dry_run: bool = Field(
        False,
        description="If True, shows what would be deleted without performing the deletion. Useful for previewing the deletion impact."
    )


class ListDatabasesInput(BaseModel):
    """Input for listing PostgreSQL databases."""
    cluster_name: str = Field(..., description="Name of the PostgreSQL cluster.")
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
    )


class CreateDatabaseInput(BaseModel):
    """Input for creating a PostgreSQL database."""
    cluster_name: str = Field(..., description="Name of the PostgreSQL cluster.")
    database_name: str = Field(
        ...,
        description="Name of the database to create.",
        pattern=r'^[a-z_][a-z0-9_]*$'
    )
    owner: str = Field(..., description="Name of the role that will own the database.")
    reclaim_policy: Literal["retain", "delete"] = Field(
        "retain",
        description="Policy for database deletion. 'retain' keeps the database when the CRD is deleted, 'delete' removes it."
    )
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
    )
    dry_run: bool = Field(
        False,
        description="If True, shows the Database CRD definition that would be created without creating it. Useful for previewing the configuration."
    )


class DeleteDatabaseInput(BaseModel):
    """Input for deleting a PostgreSQL database."""
    cluster_name: str = Field(..., description="Name of the PostgreSQL cluster.")
    database_name: str = Field(..., description="Name of the database to delete.")
    namespace: Optional[str] = Field(
        None,
        description="Kubernetes namespace where the cluster exists. If not specified, uses the current namespace from your Kubernetes context."
    )
    dry_run: bool = Field(
        False,
        description="If True, shows what would be deleted without performing the deletion. Useful for previewing the deletion impact."
    )


# ============================================================================
# MCP Tools - Implementation Functions
# ============================================================================

@mcp.tool()
async def list_postgres_clusters(
    namespace: Optional[str] = None,
    detail_level: Literal["concise", "detailed"] = "concise",
    format: Literal["text", "json"] = "text"
) -> str:
    """
    List all PostgreSQL clusters managed by CloudNativePG.

    This tool retrieves information about PostgreSQL clusters in the Kubernetes cluster.
    Use this to discover available clusters, check their health status, and understand
    the current state of your PostgreSQL infrastructure.

    Args:
        namespace: Kubernetes namespace to list clusters from. If not provided, uses
                  the current namespace from your Kubernetes context. To list clusters
                  in a different namespace, specify it explicitly.
        detail_level: Level of detail in the response. Use 'concise' for a quick
                     overview or 'detailed' for comprehensive information including
                     conditions, resources, and configurations.
        format: Output format. 'text' for human-readable (default), 'json' for structured
               data that can be programmatically consumed.

    Returns:
        A formatted string containing cluster information. Returns human-readable
        status information for each cluster including name, namespace, health status,
        number of ready instances, and current primary pod. If format='json', returns
        a JSON string with structured data.

    Examples:
        - List clusters in current namespace: list_postgres_clusters()
        - List clusters in a specific namespace: list_postgres_clusters(namespace="production")
        - Get detailed information: list_postgres_clusters(detail_level="detailed")
        - Get JSON output: list_postgres_clusters(format="json")

    Error Handling:
        - If RBAC permissions are insufficient, ensure you have 'get' and 'list'
          permissions for postgresql.cnpg.io/clusters resources in the namespace.
        - If no clusters are found, returns a message indicating empty results.
    """
    try:
        clusters = await list_cnpg_clusters(namespace)

        if not clusters:
            scope = f"in namespace '{namespace}'" if namespace else "cluster-wide"
            if format == "json":
                return json.dumps({"clusters": [], "count": 0, "scope": scope})
            return f"No PostgreSQL clusters found {scope}."

        if format == "json":
            # Return structured JSON
            cluster_list = []
            for cluster in clusters:
                metadata = cluster.get('metadata', {})
                spec = cluster.get('spec', {})
                status = cluster.get('status', {})

                cluster_data = {
                    "name": metadata.get('name', 'unknown'),
                    "namespace": metadata.get('namespace', 'unknown'),
                    "instances": spec.get('instances', 0),
                    "ready_instances": status.get('readyInstances', 0),
                    "phase": status.get('phase', 'Unknown'),
                    "current_primary": status.get('currentPrimary', 'unknown')
                }

                if detail_level == "detailed":
                    cluster_data.update({
                        "postgres_version": spec.get('imageName', 'unknown'),
                        "storage_size": spec.get('storage', {}).get('size', 'unknown'),
                        "conditions": status.get('conditions', [])
                    })

                cluster_list.append(cluster_data)

            return json.dumps({
                "clusters": cluster_list,
                "count": len(cluster_list),
                "scope": f"namespace '{namespace}'" if namespace else "all namespaces"
            }, indent=2)

        # Default: human-readable text
        result = f"Found {len(clusters)} PostgreSQL cluster(s):\n\n"

        for cluster in clusters:
            result += format_cluster_status(cluster, detail_level) + "\n"

        return truncate_response(result)

    except Exception as e:
        return format_error_message(e, "listing PostgreSQL clusters")


@mcp.tool()
async def get_cluster_status(
    name: str,
    namespace: Optional[str] = None,
    detail_level: Literal["concise", "detailed"] = "concise",
    format: Literal["text", "json"] = "text"
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
        format: Output format. 'text' for human-readable (default), 'json' for structured
               data that can be programmatically consumed.

    Returns:
        Formatted string with cluster status information including phase, ready instances,
        primary pod, PostgreSQL version, storage configuration, and detailed conditions
        if requested. If format='json', returns a JSON string with structured data.

    Examples:
        - get_cluster_status(name="main-db")  # Uses current context namespace
        - get_cluster_status(name="main-db", namespace="production")
        - get_cluster_status(name="test-db", detail_level="detailed")
        - get_cluster_status(name="main-db", format="json")

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

        if format == "json":
            # Return structured JSON
            metadata = cluster.get('metadata', {})
            spec = cluster.get('spec', {})
            status = cluster.get('status', {})

            cluster_data = {
                "name": metadata.get('name', 'unknown'),
                "namespace": metadata.get('namespace', 'unknown'),
                "instances": spec.get('instances', 0),
                "ready_instances": status.get('readyInstances', 0),
                "phase": status.get('phase', 'Unknown'),
                "current_primary": status.get('currentPrimary', 'unknown'),
                "postgres_version": spec.get('imageName', 'unknown'),
                "storage_size": spec.get('storage', {}).get('size', 'unknown')
            }

            if detail_level == "detailed":
                cluster_data.update({
                    "storage_class": spec.get('storage', {}).get('storageClass'),
                    "conditions": status.get('conditions', []),
                    "postgresql_parameters": spec.get('postgresql', {}).get('parameters', {}),
                    "managed_roles": spec.get('managed', {}).get('roles', [])
                })

            return json.dumps(cluster_data, indent=2)

        # Default: human-readable text
        result = format_cluster_status(cluster, detail_level)
        return truncate_response(result)

    except Exception as e:
        return format_error_message(e, f"getting cluster status for {namespace}/{name}")


@mcp.tool()
async def create_postgres_cluster(
    name: str,
    instances: int = 3,
    storage_size: str = "10Gi",
    postgres_version: str = "16",
    storage_class: Optional[str] = None,
    wait: bool = False,
    timeout: Optional[int] = None,
    namespace: Optional[str] = None,
    dry_run: bool = False
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
        dry_run: If True, returns the cluster definition that would be created without
                actually creating it. Useful for previewing the configuration before
                applying it. Default is False.

    Returns:
        Success message with cluster details if creation succeeds, or detailed error
        message with suggestions if it fails. If wait=True, includes final cluster status.
        If dry_run=True, returns the YAML cluster definition that would be created.

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
                }
            }
        }
        
        # Add storage class if specified
        if storage_class:
            cluster_spec["spec"]["storage"]["storageClass"] = storage_class

        # If dry_run, return the cluster definition without creating
        if dry_run:
            cluster_yaml = yaml.dump(cluster_spec, default_flow_style=False, sort_keys=False)
            return f"""Dry run: PostgreSQL cluster definition for '{name}' in namespace '{namespace}'

This is the cluster definition that would be created:

```yaml
{cluster_yaml}```

To create this cluster, call create_postgres_cluster again with dry_run=False (or omit the dry_run parameter).
"""

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


@mcp.tool()
async def scale_postgres_cluster(
    name: str,
    instances: int,
    namespace: Optional[str] = None,
    dry_run: bool = False
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
        dry_run: If True, shows what would be changed without applying it. Useful for
                previewing the scaling operation. Default is False.

    Returns:
        Success message if the scaling operation is initiated, or error details if it fails.
        If dry_run=True, returns a preview of the changes that would be made.

    Examples:
        - Scale up: scale_postgres_cluster(name="main-db", instances=5)
        - Scale with namespace: scale_postgres_cluster(name="main-db", instances=5, namespace="production")
        - Scale down: scale_postgres_cluster(name="test-db", instances=1)
        - Preview scaling: scale_postgres_cluster(name="main-db", instances=5, dry_run=True)

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
        current_instances = cluster['spec']['instances']

        # If dry_run, return preview of changes
        if dry_run:
            return f"""Dry run: Scaling operation for cluster '{namespace}/{name}'

Current configuration:
- Instances: {current_instances}

Proposed changes:
- Instances: {current_instances} → {instances}

Impact:
- {abs(instances - current_instances)} instance(s) will be {'added' if instances > current_instances else 'removed'}
- Scaling {'up' if instances > current_instances else 'down'} from {current_instances} to {instances}

To apply this change, call scale_postgres_cluster again with dry_run=False (or omit the dry_run parameter).
"""

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


@mcp.tool()
async def delete_postgres_cluster(
    name: str,
    confirm_deletion: bool = False,
    namespace: Optional[str] = None,
    dry_run: bool = False
) -> str:
    """
    Delete a PostgreSQL cluster and its associated resources.

    This tool permanently deletes a CloudNativePG cluster. This is a destructive
    operation that cannot be undone. All data will be lost unless you have backups.
    Use with caution, especially in production environments.

    Automatically cleans up:
    - The cluster resource itself
    - All associated role password secrets (labeled with cnpg.io/cluster={name})

    Args:
        name: Name of the cluster to delete.
        confirm_deletion: Must be explicitly set to True to confirm deletion.
                         This is a required safety mechanism to prevent accidental deletions.
        namespace: Kubernetes namespace where the cluster exists. If not specified,
                  uses the current namespace from your Kubernetes context.
        dry_run: If True, shows what would be deleted without performing the deletion.
                Useful for previewing the deletion impact. Default is False.

    Returns:
        Success message if deletion is initiated (including count of secrets cleaned up),
        warning message if not confirmed, or error details if it fails.
        If dry_run=True, returns a preview of what would be deleted.

    Examples:
        - Request deletion (shows warning): delete_postgres_cluster(name="old-test-cluster")
        - Confirm deletion: delete_postgres_cluster(name="old-test-cluster", confirm_deletion=True)
        - Preview deletion: delete_postgres_cluster(name="old-test-cluster", dry_run=True)

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

        # Verify cluster exists
        cluster = await get_cnpg_cluster(namespace, name)

        # If dry_run, show what would be deleted
        if dry_run:
            # Count associated secrets
            _, core_api = get_kubernetes_clients()
            label_selector = f"cnpg.io/cluster={name}"
            secrets = await asyncio.to_thread(
                core_api.list_namespaced_secret,
                namespace=namespace,
                label_selector=label_selector
            )
            secret_count = len(secrets.items)
            secret_names = [s.metadata.name for s in secrets.items]

            spec = cluster.get('spec', {})
            instances = spec.get('instances', 0)
            storage_size = spec.get('storage', {}).get('size', 'unknown')

            return f"""Dry run: Deletion preview for cluster '{namespace}/{name}'

Cluster details:
- Instances: {instances}
- Storage size per instance: {storage_size}
- Total storage: {instances}x {storage_size}

Resources that would be deleted:
- Cluster CRD: {name}
- Associated secrets: {secret_count} secret(s)
  {chr(10).join(['  - ' + s for s in secret_names]) if secret_names else '  (none)'}

⚠️  WARNING: This operation would be DESTRUCTIVE and IRREVERSIBLE:
- All data in this cluster would be PERMANENTLY LOST
- All databases, tables, and data would be deleted
- Depending on storage class policy, persistent volumes may be deleted

To proceed with deletion, call delete_postgres_cluster with confirm_deletion=True and dry_run=False (or omit dry_run).
"""

        # Check if deletion is confirmed
        if not confirm_deletion:
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

        # Delete the cluster
        custom_api, core_api = get_kubernetes_clients()
        await asyncio.to_thread(
            custom_api.delete_namespaced_custom_object,
            group=CNPG_GROUP,
            version=CNPG_VERSION,
            namespace=namespace,
            plural=CNPG_PLURAL,
            name=name
        )

        # Clean up associated role secrets
        secrets_deleted = 0
        try:
            # Find all secrets for this cluster using label selector
            label_selector = f"cnpg.io/cluster={name}"
            secrets = await asyncio.to_thread(
                core_api.list_namespaced_secret,
                namespace=namespace,
                label_selector=label_selector
            )

            # Delete each secret
            for secret in secrets.items:
                try:
                    await asyncio.to_thread(
                        core_api.delete_namespaced_secret,
                        name=secret.metadata.name,
                        namespace=namespace
                    )
                    secrets_deleted += 1
                except Exception:
                    # Continue even if a secret fails to delete
                    pass
        except Exception:
            # If secret cleanup fails, don't fail the whole operation
            pass

        secrets_msg = ""
        if secrets_deleted > 0:
            secrets_msg = f"\n\n🔑 Cleaned up {secrets_deleted} associated role secret(s)."

        return f"""Successfully initiated deletion of cluster '{namespace}/{name}'.{secrets_msg}

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


@mcp.tool()
async def list_postgres_roles(
    cluster_name: str,
    namespace: Optional[str] = None,
    format: Literal["text", "json"] = "text"
) -> str:
    """
    List all PostgreSQL roles/users managed in a cluster.

    Reads roles from the Cluster CRD's .spec.managed.roles field.

    Args:
        cluster_name: Name of the PostgreSQL cluster.
        namespace: Kubernetes namespace where the cluster exists.
        format: Output format. 'text' for human-readable (default), 'json' for structured
               data that can be programmatically consumed.

    Returns:
        Formatted list of roles with their attributes. If format='json', returns a JSON
        string with structured data.
    """
    try:
        if namespace is None:
            namespace = get_current_namespace()

        # Get the cluster to read managed roles
        cluster = await get_cnpg_cluster(namespace, cluster_name)
        managed_roles = cluster.get('spec', {}).get('managed', {}).get('roles', [])

        if not managed_roles:
            if format == "json":
                return json.dumps({
                    "cluster": f"{namespace}/{cluster_name}",
                    "roles": [],
                    "count": 0
                })
            return f"No managed roles defined in cluster '{namespace}/{cluster_name}'.\n\nRoles are managed through the Cluster CRD's .spec.managed.roles field."

        if format == "json":
            # Return structured JSON
            role_list = []
            for role in managed_roles:
                role_data = {
                    "name": role.get('name', 'unknown'),
                    "ensure": role.get('ensure', 'present'),
                    "login": role.get('login', False),
                    "superuser": role.get('superuser', False),
                    "inherit": role.get('inherit', True),
                    "createdb": role.get('createdb', False),
                    "createrole": role.get('createrole', False),
                    "replication": role.get('replication', False),
                    "password_secret": role.get('passwordSecret', {}).get('name', 'none'),
                    "in_roles": role.get('inRoles', [])
                }
                role_list.append(role_data)

            return json.dumps({
                "cluster": f"{namespace}/{cluster_name}",
                "roles": role_list,
                "count": len(role_list)
            }, indent=2)

        # Default: human-readable text
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


@mcp.tool()
async def create_postgres_role(
    cluster_name: str,
    role_name: str,
    login: bool = True,
    superuser: bool = False,
    inherit: bool = True,
    createdb: bool = False,
    createrole: bool = False,
    replication: bool = False,
    namespace: Optional[str] = None,
    dry_run: bool = False
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
        dry_run: If True, shows the role definition that would be created without
                creating it. Useful for previewing the configuration. Default is False.

    Returns:
        Success message with password retrieval instructions.
        If dry_run=True, returns a preview of the role definition.
    """
    try:
        if namespace is None:
            namespace = get_current_namespace()

        # Get the cluster to verify it exists and check for existing role
        cluster = await get_cnpg_cluster(namespace, cluster_name)
        managed_roles = cluster.get('spec', {}).get('managed', {}).get('roles', [])

        # Check if role already exists
        existing_role = next((r for r in managed_roles if r.get('name') == role_name), None)
        if existing_role:
            return f"Error: Role '{role_name}' already exists in cluster '{namespace}/{cluster_name}'."

        # If dry_run, show what would be created
        if dry_run:
            secret_name = f"cnpg-{cluster_name}-user-{role_name}"

            role_def = {
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

            role_yaml = yaml.dump(role_def, default_flow_style=False, sort_keys=False)

            return f"""Dry run: PostgreSQL role definition for '{role_name}' in cluster '{namespace}/{cluster_name}'

Role definition that would be added to .spec.managed.roles:

```yaml
{role_yaml}```

Resources that would be created:
- Kubernetes secret: {secret_name}
  - Contains auto-generated password (16 characters)
  - Labeled with cnpg.io/cluster={cluster_name} and cnpg.io/role={role_name}

Role Attributes:
- Login: {login}
- Superuser: {superuser}
- Inherit: {inherit}
- Create DB: {createdb}
- Create Role: {createrole}
- Replication: {replication}

To create this role, call create_postgres_role again with dry_run=False (or omit the dry_run parameter).
"""

        # Generate a secure password
        password = generate_password(16)

        # Create Kubernetes secret to store the password
        secret_name = f"cnpg-{cluster_name}-user-{role_name}"
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

        # Ensure managed.roles exists
        if 'managed' not in cluster['spec']:
            cluster['spec']['managed'] = {}
        if 'roles' not in cluster['spec']['managed']:
            cluster['spec']['managed']['roles'] = []

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


@mcp.tool()
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
    namespace: Optional[str] = None,
    dry_run: bool = False
) -> str:
    """
    Update attributes of an existing PostgreSQL role using CloudNativePG's declarative role management.

    Args:
        cluster_name: Name of the PostgreSQL cluster.
        role_name: Name of the role to update.
        login, superuser, inherit, createdb, createrole, replication: Optional attribute changes.
        password: Optional new password. If not provided, password remains unchanged.
        namespace: Kubernetes namespace.
        dry_run: If True, shows what changes would be made without applying them.
                Useful for previewing the update. Default is False.

    Returns:
        Success message with updated attributes.
        If dry_run=True, returns a preview of the changes that would be made.
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

        # Build list of proposed updates
        if login is not None:
            updates.append((f"Login: {role.get('login', False)} → {login}", 'login', login))

        if superuser is not None:
            updates.append((f"Superuser: {role.get('superuser', False)} → {superuser}", 'superuser', superuser))

        if inherit is not None:
            updates.append((f"Inherit: {role.get('inherit', True)} → {inherit}", 'inherit', inherit))

        if createdb is not None:
            updates.append((f"Create DB: {role.get('createdb', False)} → {createdb}", 'createdb', createdb))

        if createrole is not None:
            updates.append((f"Create Role: {role.get('createrole', False)} → {createrole}", 'createrole', createrole))

        if replication is not None:
            updates.append((f"Replication: {role.get('replication', False)} → {replication}", 'replication', replication))

        if password is not None:
            updates.append(("Password: will be updated", 'password', password))

        if not updates:
            return "No updates specified. Please provide at least one attribute to update."

        # If dry_run, show what would change
        if dry_run:
            update_text = '\n- '.join([u[0] for u in updates])
            return f"""Dry run: Update preview for role '{role_name}' in cluster '{namespace}/{cluster_name}'

Current attributes:
- Login: {role.get('login', False)}
- Superuser: {role.get('superuser', False)}
- Inherit: {role.get('inherit', True)}
- Create DB: {role.get('createdb', False)}
- Create Role: {role.get('createrole', False)}
- Replication: {role.get('replication', False)}

Proposed changes:
- {update_text}

To apply these changes, call update_postgres_role again with dry_run=False (or omit the dry_run parameter).
"""

        # Apply updates
        simple_updates = []
        for update_desc, attr_name, value in updates:
            if attr_name == 'password':
                # Update the secret
                secret_name = f"cnpg-{cluster_name}-user-{role_name}"
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
                    simple_updates.append("Password: updated")
                except ApiException as e:
                    return f"Error: Secret '{secret_name}' not found. Cannot update password."
            else:
                # Update role attribute
                role[attr_name] = value
                simple_updates.append(update_desc)

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

        updates_text = '\n- '.join(simple_updates)
        return f"""Successfully updated PostgreSQL role '{role_name}' in cluster '{namespace}/{cluster_name}'.

Updated Attributes:
- {updates_text}

The CloudNativePG operator will reconcile these changes in the database.
"""

    except Exception as e:
        return format_error_message(e, f"updating role {role_name} in cluster {namespace}/{cluster_name}")


@mcp.tool()
async def delete_postgres_role(
    cluster_name: str,
    role_name: str,
    namespace: Optional[str] = None,
    dry_run: bool = False
) -> str:
    """
    Delete a PostgreSQL role from a cluster using CloudNativePG's declarative role management.

    Sets the role's ensure field to 'absent' or removes it from .spec.managed.roles.
    Also deletes the associated Kubernetes secret.

    Args:
        cluster_name: Name of the PostgreSQL cluster.
        role_name: Name of the role to delete.
        namespace: Kubernetes namespace.
        dry_run: If True, shows what would be deleted without performing the deletion.
                Useful for previewing the deletion impact. Default is False.

    Returns:
        Success message.
        If dry_run=True, returns a preview of what would be deleted.
    """
    try:
        if namespace is None:
            namespace = get_current_namespace()

        # Get the cluster
        cluster = await get_cnpg_cluster(namespace, cluster_name)
        managed_roles = cluster.get('spec', {}).get('managed', {}).get('roles', [])

        # Find the role
        role_index = next((i for i, r in enumerate(managed_roles) if r.get('name') == role_name), None)
        if role_index is None:
            return f"Error: Role '{role_name}' not found in cluster '{namespace}/{cluster_name}'."

        role = managed_roles[role_index]

        # If dry_run, show what would be deleted
        if dry_run:
            secret_name = f"cnpg-{cluster_name}-user-{role_name}"

            # Check if secret exists
            _, core_api = get_kubernetes_clients()
            try:
                await asyncio.to_thread(
                    core_api.read_namespaced_secret,
                    name=secret_name,
                    namespace=namespace
                )
                secret_exists = True
            except ApiException:
                secret_exists = False

            return f"""Dry run: Deletion preview for role '{role_name}' in cluster '{namespace}/{cluster_name}'

Role details:
- Login: {role.get('login', False)}
- Superuser: {role.get('superuser', False)}
- Inherit: {role.get('inherit', True)}
- Create DB: {role.get('createdb', False)}
- Create Role: {role.get('createrole', False)}
- Replication: {role.get('replication', False)}

Resources that would be deleted:
- Role definition from .spec.managed.roles in cluster CRD
- Kubernetes secret: {secret_name} {'(exists)' if secret_exists else '(not found)'}

⚠️  WARNING: This operation will drop the role from PostgreSQL.
Any objects owned by this role or permissions granted to it will be affected.

To proceed with deletion, call delete_postgres_role again with dry_run=False (or omit the dry_run parameter).
"""

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
        secret_name = f"cnpg-{cluster_name}-user-{role_name}"
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


@mcp.tool()
async def list_postgres_databases(
    cluster_name: str,
    namespace: Optional[str] = None,
    format: Literal["text", "json"] = "text"
) -> str:
    """
    List all PostgreSQL databases managed by Database CRDs for a cluster.

    Args:
        cluster_name: Name of the PostgreSQL cluster.
        namespace: Kubernetes namespace where the cluster exists.
        format: Output format. 'text' for human-readable (default), 'json' for structured
               data that can be programmatically consumed.

    Returns:
        Formatted list of databases with their details. If format='json', returns a JSON
        string with structured data.
    """
    try:
        if namespace is None:
            namespace = get_current_namespace()

        # List all Database CRDs in the namespace
        custom_api, _ = get_kubernetes_clients()
        databases = await asyncio.to_thread(
            custom_api.list_namespaced_custom_object,
            group=CNPG_GROUP,
            version=CNPG_VERSION,
            namespace=namespace,
            plural=CNPG_DATABASE_PLURAL
        )

        # Filter for databases belonging to this cluster
        cluster_databases = [
            db for db in databases.get('items', [])
            if db.get('spec', {}).get('cluster', {}).get('name') == cluster_name
        ]

        if not cluster_databases:
            if format == "json":
                return json.dumps({
                    "cluster": f"{namespace}/{cluster_name}",
                    "databases": [],
                    "count": 0
                })
            return f"No managed databases found for cluster '{namespace}/{cluster_name}'.\n\nDatabases are managed through Database CRDs."

        if format == "json":
            # Return structured JSON
            database_list = []
            for db in cluster_databases:
                spec = db.get('spec', {})
                metadata = db.get('metadata', {})

                db_data = {
                    "crd_name": metadata.get('name', 'unknown'),
                    "database_name": spec.get('name', 'unknown'),
                    "owner": spec.get('owner', 'unknown'),
                    "ensure": spec.get('ensure', 'present'),
                    "reclaim_policy": spec.get('databaseReclaimPolicy', 'retain')
                }
                database_list.append(db_data)

            return json.dumps({
                "cluster": f"{namespace}/{cluster_name}",
                "databases": database_list,
                "count": len(database_list)
            }, indent=2)

        # Default: human-readable text
        result = f"PostgreSQL Databases for cluster '{namespace}/{cluster_name}':\n\n"

        for db in cluster_databases:
            spec = db.get('spec', {})
            metadata = db.get('metadata', {})

            crd_name = metadata.get('name', 'unknown')
            db_name = spec.get('name', 'unknown')
            owner = spec.get('owner', 'unknown')
            ensure = spec.get('ensure', 'present')
            reclaim_policy = spec.get('databaseReclaimPolicy', 'retain')

            result += f"**{db_name}** (CRD: {crd_name})\n"
            result += f"  - Owner: {owner}\n"
            result += f"  - Ensure: {ensure}\n"
            result += f"  - Reclaim Policy: {reclaim_policy}\n"
            result += "\n"

        return result

    except Exception as e:
        return format_error_message(e, f"listing databases for cluster {namespace}/{cluster_name}")


@mcp.tool()
async def create_postgres_database(
    cluster_name: str,
    database_name: str,
    owner: str,
    reclaim_policy: Literal["retain", "delete"] = "retain",
    namespace: Optional[str] = None,
    dry_run: bool = False
) -> str:
    """
    Create a new PostgreSQL database using CloudNativePG's Database CRD.

    Creates a Database custom resource that the CloudNativePG operator will reconcile.

    Args:
        cluster_name: Name of the PostgreSQL cluster.
        database_name: Name of the database to create.
        owner: Name of the role that will own the database.
        reclaim_policy: 'retain' to keep database after CRD deletion, 'delete' to remove it.
        namespace: Kubernetes namespace.
        dry_run: If True, shows the Database CRD definition that would be created without
                creating it. Useful for previewing the configuration. Default is False.

    Returns:
        Success message with database details.
        If dry_run=True, returns a preview of the Database CRD definition.
    """
    try:
        if namespace is None:
            namespace = get_current_namespace()

        # Create a unique CRD name (cluster-database)
        crd_name = f"{cluster_name}-{database_name}"

        # Build the Database CRD
        database_crd = {
            "apiVersion": f"{CNPG_GROUP}/{CNPG_VERSION}",
            "kind": "Database",
            "metadata": {
                "name": crd_name,
                "namespace": namespace,
                "labels": {
                    "cnpg.io/cluster": cluster_name,
                    "cnpg.io/database": database_name
                }
            },
            "spec": {
                "name": database_name,
                "owner": owner,
                "cluster": {
                    "name": cluster_name
                },
                "ensure": "present",
                "databaseReclaimPolicy": reclaim_policy
            }
        }

        # If dry_run, return the Database CRD definition
        if dry_run:
            database_yaml = yaml.dump(database_crd, default_flow_style=False, sort_keys=False)
            return f"""Dry run: Database CRD definition for '{database_name}' in cluster '{namespace}/{cluster_name}'

This is the Database CRD that would be created:

```yaml
{database_yaml}```

Database Details:
- Name: {database_name}
- Owner: {owner}
- Reclaim Policy: {reclaim_policy}
- CRD Name: {crd_name}

Reclaim Policy Behavior:
- retain: Database will be kept in PostgreSQL even if the CRD is deleted
- delete: Database will be dropped from PostgreSQL when the CRD is deleted

To create this database, call create_postgres_database again with dry_run=False (or omit the dry_run parameter).
"""

        # Create the Database CRD
        custom_api, _ = get_kubernetes_clients()
        await asyncio.to_thread(
            custom_api.create_namespaced_custom_object,
            group=CNPG_GROUP,
            version=CNPG_VERSION,
            namespace=namespace,
            plural=CNPG_DATABASE_PLURAL,
            body=database_crd
        )

        return f"""Successfully created Database CRD for '{database_name}' in cluster '{namespace}/{cluster_name}'.

Database Details:
- Name: {database_name}
- Owner: {owner}
- Reclaim Policy: {reclaim_policy}
- CRD Name: {crd_name}

The CloudNativePG operator will create this database in the cluster.

To view the database status:
kubectl get database {crd_name} -n {namespace}
"""

    except Exception as e:
        return format_error_message(e, f"creating database {database_name} in cluster {namespace}/{cluster_name}")


@mcp.tool()
async def delete_postgres_database(
    cluster_name: str,
    database_name: str,
    namespace: Optional[str] = None,
    dry_run: bool = False
) -> str:
    """
    Delete a PostgreSQL database by removing its Database CRD.

    Whether the database is actually dropped from PostgreSQL depends on the
    databaseReclaimPolicy set when the database was created.

    Args:
        cluster_name: Name of the PostgreSQL cluster.
        database_name: Name of the database to delete.
        namespace: Kubernetes namespace.
        dry_run: If True, shows what would be deleted without performing the deletion.
                Useful for previewing the deletion impact. Default is False.

    Returns:
        Success message.
        If dry_run=True, returns a preview of what would be deleted.
    """
    try:
        if namespace is None:
            namespace = get_current_namespace()

        # Find the Database CRD
        crd_name = f"{cluster_name}-{database_name}"

        custom_api, _ = get_kubernetes_clients()

        # Get the database to check reclaim policy
        try:
            database_crd = await asyncio.to_thread(
                custom_api.get_namespaced_custom_object,
                group=CNPG_GROUP,
                version=CNPG_VERSION,
                namespace=namespace,
                plural=CNPG_DATABASE_PLURAL,
                name=crd_name
            )
            spec = database_crd.get('spec', {})
            reclaim_policy = spec.get('databaseReclaimPolicy', 'retain')
            owner = spec.get('owner', 'unknown')
        except ApiException as e:
            if e.status == 404:
                return f"Error: Database CRD '{crd_name}' not found for database '{database_name}' in cluster '{namespace}/{cluster_name}'."
            raise

        # If dry_run, show what would be deleted
        if dry_run:
            action = "dropped from PostgreSQL" if reclaim_policy == "delete" else "retained in PostgreSQL"

            return f"""Dry run: Deletion preview for database '{database_name}' in cluster '{namespace}/{cluster_name}'

Database Details:
- Name: {database_name}
- Owner: {owner}
- Reclaim Policy: {reclaim_policy}
- CRD Name: {crd_name}

Resources that would be deleted:
- Database CRD: {crd_name}

Impact based on reclaim policy:
- Reclaim Policy: {reclaim_policy}
- Result: The database will be {action}

Reclaim Policy Behavior:
- retain: Database CRD is deleted but the database remains in PostgreSQL
- delete: Database CRD is deleted AND the database is dropped from PostgreSQL

⚠️  WARNING: If reclaim_policy is 'delete', all data in this database will be PERMANENTLY LOST.

To proceed with deletion, call delete_postgres_database again with dry_run=False (or omit the dry_run parameter).
"""

        # Delete the Database CRD
        await asyncio.to_thread(
            custom_api.delete_namespaced_custom_object,
            group=CNPG_GROUP,
            version=CNPG_VERSION,
            namespace=namespace,
            plural=CNPG_DATABASE_PLURAL,
            name=crd_name
        )

        action = "will be dropped from PostgreSQL" if reclaim_policy == "delete" else "will be retained in PostgreSQL"

        return f"""Successfully deleted Database CRD '{crd_name}' for database '{database_name}'.

Reclaim Policy: {reclaim_policy}
Result: The database {action}.

The CloudNativePG operator will reconcile this change.
"""

    except Exception as e:
        return format_error_message(e, f"deleting database {database_name} from cluster {namespace}/{cluster_name}")


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
# Note: FastMCP Auto-generates Tool Schemas
# ============================================================================
# With FastMCP, we don't need to manually define:
# - @mcp.list_tools() - schemas are auto-generated from function signatures
# - @mcp.call_tool() - routing is automatic based on function names
# - Resource/Prompt handlers - not needed unless we explicitly use them
#
# All @mcp.tool() decorated functions below are automatically registered!


# ============================================================================
# Transport Layer
# ============================================================================

async def run_stdio_transport():
    """
    Run the MCP server using stdio transport.

    This is the default mode for local usage with Claude Desktop.
    The server communicates via stdin/stdout and is managed as a child process.

    FastMCP simplifies this - use run_stdio_async() for existing event loops!
    """
    print("Starting CloudNativePG MCP server with stdio transport...", file=sys.stderr)
    print(f"Python version: {sys.version}", file=sys.stderr)
    print(f"FastMCP server initialized with name: cloudnative-pg", file=sys.stderr)

    # Use run_stdio_async() since we're already in an asyncio event loop
    await mcp.run_stdio_async()


async def run_http_transport(host: str = "0.0.0.0", port: int = 4204):
    """
    Run the MCP server using HTTP transport (Streamable HTTP) with OIDC authentication.

    This mode allows multiple clients to connect remotely and is suitable
    for team environments and production deployments. The MCP endpoint is
    available at /mcp.

    OIDC authentication is enforced via environment variables:
        OIDC_ISSUER: OIDC provider URL (required)
        OIDC_AUDIENCE: Expected JWT audience (required)
        OIDC_JWKS_URI: Optional JWKS URI override
        DCR_PROXY_URL: Optional DCR proxy for client registration
        OIDC_SCOPE: Required scope (default: openid)
    """
    print(f"Starting CloudNativePG MCP server with HTTP transport on {host}:{port}...", file=sys.stderr)
    print(f"FastMCP server initialized with name: cloudnative-pg", file=sys.stderr)
    print(f"MCP endpoint available at: http://{host}:{port}/mcp", file=sys.stderr)

    # Initialize OIDC authentication if configured
    auth_provider = None
    middleware = []

    # Check if OIDC should be enabled (config file or env var)
    import os
    from pathlib import Path
    oidc_config_exists = Path("/etc/mcp/oidc.yaml").exists() or os.getenv("OIDC_ISSUER")

    if oidc_config_exists:
        try:
            from auth_oidc import OIDCAuthProvider, OIDCAuthMiddleware
            from starlette.middleware import Middleware

            print("Initializing OIDC authentication...", file=sys.stderr)
            # OIDCAuthProvider will check config file first, then env vars
            auth_provider = OIDCAuthProvider()

            # Create middleware using Starlette's Middleware wrapper
            # This is the format Starlette expects when building middleware stack
            middleware.append(
                Middleware(
                    OIDCAuthMiddleware,
                    auth_provider=auth_provider,
                    exclude_paths=["/healthz", "/readyz", "/.well-known/"]
                )
            )

            print(f"✓ OIDC authentication enabled", file=sys.stderr)
            print(f"  Issuer: {auth_provider.issuer}", file=sys.stderr)
            print(f"  Audience: {auth_provider.audience}", file=sys.stderr)

        except Exception as e:
            print(f"ERROR: Failed to initialize OIDC authentication: {e}", file=sys.stderr)
            print("Server will NOT start without valid OIDC configuration.", file=sys.stderr)
            raise
    else:
        print("WARNING: OIDC authentication NOT configured!", file=sys.stderr)
        print("Provide OIDC config via:", file=sys.stderr)
        print("  1. Config file at /etc/mcp/oidc.yaml (recommended for Kubernetes)", file=sys.stderr)
        print("  2. Environment variables: OIDC_ISSUER and OIDC_AUDIENCE", file=sys.stderr)
        print("Running in INSECURE mode (development only).", file=sys.stderr)

    # Get Starlette app without middleware
    # Use "http" transport (Streamable HTTP) with /mcp endpoint
    # This is the recommended transport for production deployments
    app = mcp.http_app(
        transport="http",
        path="/mcp"
    )

    # Add health check endpoints (unauthenticated) - must be added before wrapping with auth
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def liveness_check(request):
        """Liveness probe - checks if server is running."""
        return JSONResponse({"status": "alive", "service": "cnpg-mcp-server"})

    async def readiness_check(request):
        """Readiness probe - checks if server is ready to accept requests."""
        # TODO: Add checks for Kubernetes API connectivity if needed
        return JSONResponse({"status": "ready", "service": "cnpg-mcp-server"})

    app.routes.insert(0, Route("/healthz", liveness_check, methods=["GET"]))
    app.routes.insert(0, Route("/readyz", readiness_check, methods=["GET"]))

    # Add OAuth metadata routes if auth provider is configured
    if auth_provider:
        metadata_routes = auth_provider.get_metadata_routes()
        for route in metadata_routes:
            app.routes.append(route)

    # Wrap the app with OIDC middleware if configured
    # This must be done AFTER adding all routes
    if middleware:
        from starlette.middleware import Middleware
        from starlette.applications import Starlette

        # Extract the OIDC middleware config
        oidc_middleware_config = middleware[0]

        # Apply middleware by wrapping the app
        app.add_middleware(
            oidc_middleware_config.cls,
            **oidc_middleware_config.kwargs
        )

    # Run with uvicorn
    import uvicorn

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
        server_header=False,
    )

    server = uvicorn.Server(config)
    await server.serve()


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
        default=4204,
        help="Port to listen on (HTTP transport only, default: 4204)"
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


def run():
    """Synchronous entry point for setup.py console_scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
