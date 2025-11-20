#!/usr/bin/env python3
"""
CloudNativePG MCP Server - RBAC Setup Script

This script creates the necessary Kubernetes RBAC resources for the CloudNativePG
MCP server to interact with PostgreSQL clusters.

Usage:
    python setup_rbac.py --namespace default --service-account cnpg-mcp-server
    python setup_rbac.py --namespace production --scope namespace
    python setup_rbac.py --dry-run  # See what would be created
    python setup_rbac.py --delete  # Remove RBAC resources
"""

import argparse
import sys
from typing import Optional, Dict, Any, List

from kubernetes import client, config
from kubernetes.client.rest import ApiException


# ============================================================================
# RBAC Resource Definitions
# ============================================================================

def get_service_account(namespace: str, name: str) -> Dict[str, Any]:
    """Generate ServiceAccount manifest."""
    return {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": "cnpg-mcp-server",
                "component": "rbac"
            }
        }
    }


def get_cluster_role(name: str) -> Dict[str, Any]:
    """Generate ClusterRole manifest for cluster-wide access."""
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRole",
        "metadata": {
            "name": name,
            "labels": {
                "app": "cnpg-mcp-server",
                "component": "rbac"
            }
        },
        "rules": [
            {
                "apiGroups": ["postgresql.cnpg.io"],
                "resources": ["clusters", "backups", "scheduledbackups", "poolers"],
                "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"]
            },
            {
                "apiGroups": [""],
                "resources": ["events"],
                "verbs": ["get", "list", "watch"]
            },
            {
                "apiGroups": [""],
                "resources": ["pods", "pods/log"],
                "verbs": ["get", "list", "watch"]
            },
            {
                "apiGroups": [""],
                "resources": ["secrets"],
                "verbs": ["get", "list", "create", "update", "patch"]
            },
            {
                "apiGroups": [""],
                "resources": ["persistentvolumeclaims"],
                "verbs": ["get", "list", "watch"]
            },
            {
                "apiGroups": [""],
                "resources": ["services"],
                "verbs": ["get", "list", "watch"]
            }
        ]
    }


def get_role(namespace: str, name: str) -> Dict[str, Any]:
    """Generate Role manifest for namespace-scoped access."""
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "Role",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": "cnpg-mcp-server",
                "component": "rbac"
            }
        },
        "rules": [
            {
                "apiGroups": ["postgresql.cnpg.io"],
                "resources": ["clusters", "backups", "scheduledbackups", "poolers"],
                "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"]
            },
            {
                "apiGroups": [""],
                "resources": ["events", "pods", "pods/log", "secrets", "persistentvolumeclaims", "services"],
                "verbs": ["get", "list", "watch", "create", "update", "patch"]
            }
        ]
    }


def get_cluster_role_binding(
    name: str,
    service_account_name: str,
    service_account_namespace: str,
    cluster_role_name: str
) -> Dict[str, Any]:
    """Generate ClusterRoleBinding manifest."""
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRoleBinding",
        "metadata": {
            "name": name,
            "labels": {
                "app": "cnpg-mcp-server",
                "component": "rbac"
            }
        },
        "subjects": [
            {
                "kind": "ServiceAccount",
                "name": service_account_name,
                "namespace": service_account_namespace
            }
        ],
        "roleRef": {
            "kind": "ClusterRole",
            "name": cluster_role_name,
            "apiGroup": "rbac.authorization.k8s.io"
        }
    }


def get_role_binding(
    namespace: str,
    name: str,
    service_account_name: str,
    role_name: str
) -> Dict[str, Any]:
    """Generate RoleBinding manifest."""
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": "cnpg-mcp-server",
                "component": "rbac"
            }
        },
        "subjects": [
            {
                "kind": "ServiceAccount",
                "name": service_account_name,
                "namespace": namespace
            }
        ],
        "roleRef": {
            "kind": "Role",
            "name": role_name,
            "apiGroup": "rbac.authorization.k8s.io"
        }
    }


# ============================================================================
# Resource Management Functions
# ============================================================================

class RBACManager:
    """Manages RBAC resources for CloudNativePG MCP server."""
    
    def __init__(self, dry_run: bool = False):
        """Initialize the RBAC manager."""
        self.dry_run = dry_run
        
        # Initialize Kubernetes clients
        try:
            config.load_incluster_config()
            print("✓ Loaded in-cluster Kubernetes config")
        except config.ConfigException:
            try:
                config.load_kube_config()
                print("✓ Loaded kubeconfig from file")
            except Exception as e:
                print(f"✗ Failed to load Kubernetes config: {e}", file=sys.stderr)
                raise
        
        self.core_v1 = client.CoreV1Api()
        self.rbac_v1 = client.RbacAuthorizationV1Api()
    
    def create_service_account(self, namespace: str, name: str) -> bool:
        """Create a ServiceAccount."""
        try:
            sa = get_service_account(namespace, name)
            
            if self.dry_run:
                print(f"\n[DRY RUN] Would create ServiceAccount: {namespace}/{name}")
                return True
            
            # Check if already exists
            try:
                self.core_v1.read_namespaced_service_account(name, namespace)
                print(f"✓ ServiceAccount {namespace}/{name} already exists")
                return True
            except ApiException as e:
                if e.status != 404:
                    raise
            
            # Create the ServiceAccount
            self.core_v1.create_namespaced_service_account(namespace, sa)
            print(f"✓ Created ServiceAccount: {namespace}/{name}")
            return True
            
        except ApiException as e:
            print(f"✗ Failed to create ServiceAccount {namespace}/{name}: {e.reason}", file=sys.stderr)
            if e.status == 403:
                print("  Hint: You may need cluster-admin permissions to create ServiceAccounts", file=sys.stderr)
            return False
    
    def create_cluster_role(self, name: str) -> bool:
        """Create a ClusterRole."""
        try:
            role = get_cluster_role(name)
            
            if self.dry_run:
                print(f"\n[DRY RUN] Would create ClusterRole: {name}")
                return True
            
            # Check if already exists
            try:
                self.rbac_v1.read_cluster_role(name)
                print(f"✓ ClusterRole {name} already exists")
                return True
            except ApiException as e:
                if e.status != 404:
                    raise
            
            # Create the ClusterRole
            self.rbac_v1.create_cluster_role(role)
            print(f"✓ Created ClusterRole: {name}")
            return True
            
        except ApiException as e:
            print(f"✗ Failed to create ClusterRole {name}: {e.reason}", file=sys.stderr)
            if e.status == 403:
                print("  Hint: You need cluster-admin permissions to create ClusterRoles", file=sys.stderr)
            return False
    
    def create_role(self, namespace: str, name: str) -> bool:
        """Create a namespace-scoped Role."""
        try:
            role = get_role(namespace, name)
            
            if self.dry_run:
                print(f"\n[DRY RUN] Would create Role: {namespace}/{name}")
                return True
            
            # Check if already exists
            try:
                self.rbac_v1.read_namespaced_role(name, namespace)
                print(f"✓ Role {namespace}/{name} already exists")
                return True
            except ApiException as e:
                if e.status != 404:
                    raise
            
            # Create the Role
            self.rbac_v1.create_namespaced_role(namespace, role)
            print(f"✓ Created Role: {namespace}/{name}")
            return True
            
        except ApiException as e:
            print(f"✗ Failed to create Role {namespace}/{name}: {e.reason}", file=sys.stderr)
            if e.status == 403:
                print("  Hint: You may need admin permissions in the namespace", file=sys.stderr)
            return False
    
    def create_cluster_role_binding(
        self,
        name: str,
        service_account_name: str,
        service_account_namespace: str,
        cluster_role_name: str
    ) -> bool:
        """Create a ClusterRoleBinding."""
        try:
            binding = get_cluster_role_binding(
                name,
                service_account_name,
                service_account_namespace,
                cluster_role_name
            )
            
            if self.dry_run:
                print(f"\n[DRY RUN] Would create ClusterRoleBinding: {name}")
                print(f"  Subject: ServiceAccount {service_account_namespace}/{service_account_name}")
                print(f"  Role: ClusterRole {cluster_role_name}")
                return True
            
            # Check if already exists
            try:
                self.rbac_v1.read_cluster_role_binding(name)
                print(f"✓ ClusterRoleBinding {name} already exists")
                return True
            except ApiException as e:
                if e.status != 404:
                    raise
            
            # Create the ClusterRoleBinding
            self.rbac_v1.create_cluster_role_binding(binding)
            print(f"✓ Created ClusterRoleBinding: {name}")
            return True
            
        except ApiException as e:
            print(f"✗ Failed to create ClusterRoleBinding {name}: {e.reason}", file=sys.stderr)
            if e.status == 403:
                print("  Hint: You need cluster-admin permissions to create ClusterRoleBindings", file=sys.stderr)
            return False
    
    def create_role_binding(
        self,
        namespace: str,
        name: str,
        service_account_name: str,
        role_name: str
    ) -> bool:
        """Create a namespace-scoped RoleBinding."""
        try:
            binding = get_role_binding(namespace, name, service_account_name, role_name)
            
            if self.dry_run:
                print(f"\n[DRY RUN] Would create RoleBinding: {namespace}/{name}")
                print(f"  Subject: ServiceAccount {namespace}/{service_account_name}")
                print(f"  Role: Role {namespace}/{role_name}")
                return True
            
            # Check if already exists
            try:
                self.rbac_v1.read_namespaced_role_binding(name, namespace)
                print(f"✓ RoleBinding {namespace}/{name} already exists")
                return True
            except ApiException as e:
                if e.status != 404:
                    raise
            
            # Create the RoleBinding
            self.rbac_v1.create_namespaced_role_binding(namespace, binding)
            print(f"✓ Created RoleBinding: {namespace}/{name}")
            return True
            
        except ApiException as e:
            print(f"✗ Failed to create RoleBinding {namespace}/{name}: {e.reason}", file=sys.stderr)
            if e.status == 403:
                print("  Hint: You may need admin permissions in the namespace", file=sys.stderr)
            return False
    
    def delete_service_account(self, namespace: str, name: str) -> bool:
        """Delete a ServiceAccount."""
        try:
            if self.dry_run:
                print(f"\n[DRY RUN] Would delete ServiceAccount: {namespace}/{name}")
                return True
            
            self.core_v1.delete_namespaced_service_account(name, namespace)
            print(f"✓ Deleted ServiceAccount: {namespace}/{name}")
            return True
            
        except ApiException as e:
            if e.status == 404:
                print(f"✓ ServiceAccount {namespace}/{name} does not exist (already deleted)")
                return True
            print(f"✗ Failed to delete ServiceAccount {namespace}/{name}: {e.reason}", file=sys.stderr)
            return False
    
    def delete_cluster_role(self, name: str) -> bool:
        """Delete a ClusterRole."""
        try:
            if self.dry_run:
                print(f"\n[DRY RUN] Would delete ClusterRole: {name}")
                return True
            
            self.rbac_v1.delete_cluster_role(name)
            print(f"✓ Deleted ClusterRole: {name}")
            return True
            
        except ApiException as e:
            if e.status == 404:
                print(f"✓ ClusterRole {name} does not exist (already deleted)")
                return True
            print(f"✗ Failed to delete ClusterRole {name}: {e.reason}", file=sys.stderr)
            return False
    
    def delete_role(self, namespace: str, name: str) -> bool:
        """Delete a Role."""
        try:
            if self.dry_run:
                print(f"\n[DRY RUN] Would delete Role: {namespace}/{name}")
                return True
            
            self.rbac_v1.delete_namespaced_role(name, namespace)
            print(f"✓ Deleted Role: {namespace}/{name}")
            return True
            
        except ApiException as e:
            if e.status == 404:
                print(f"✓ Role {namespace}/{name} does not exist (already deleted)")
                return True
            print(f"✗ Failed to delete Role {namespace}/{name}: {e.reason}", file=sys.stderr)
            return False
    
    def delete_cluster_role_binding(self, name: str) -> bool:
        """Delete a ClusterRoleBinding."""
        try:
            if self.dry_run:
                print(f"\n[DRY RUN] Would delete ClusterRoleBinding: {name}")
                return True
            
            self.rbac_v1.delete_cluster_role_binding(name)
            print(f"✓ Deleted ClusterRoleBinding: {name}")
            return True
            
        except ApiException as e:
            if e.status == 404:
                print(f"✓ ClusterRoleBinding {name} does not exist (already deleted)")
                return True
            print(f"✗ Failed to delete ClusterRoleBinding {name}: {e.reason}", file=sys.stderr)
            return False
    
    def delete_role_binding(self, namespace: str, name: str) -> bool:
        """Delete a RoleBinding."""
        try:
            if self.dry_run:
                print(f"\n[DRY RUN] Would delete RoleBinding: {namespace}/{name}")
                return True
            
            self.rbac_v1.delete_namespaced_role_binding(name, namespace)
            print(f"✓ Deleted RoleBinding: {namespace}/{name}")
            return True
            
        except ApiException as e:
            if e.status == 404:
                print(f"✓ RoleBinding {namespace}/{name} does not exist (already deleted)")
                return True
            print(f"✗ Failed to delete RoleBinding {namespace}/{name}: {e.reason}", file=sys.stderr)
            return False


# ============================================================================
# Main Setup and Teardown Functions
# ============================================================================

def setup_rbac(
    namespace: str,
    service_account: str,
    scope: str,
    dry_run: bool = False
) -> bool:
    """
    Set up RBAC resources for CloudNativePG MCP server.
    
    Args:
        namespace: Kubernetes namespace for the service account
        service_account: Name of the service account
        scope: Either 'cluster' for cluster-wide or 'namespace' for namespace-scoped
        dry_run: If True, only show what would be created
    
    Returns:
        True if all resources were created successfully, False otherwise
    """
    print("\n" + "="*60)
    print("CloudNativePG MCP Server - RBAC Setup")
    print("="*60)
    print(f"\nConfiguration:")
    print(f"  Namespace: {namespace}")
    print(f"  Service Account: {service_account}")
    print(f"  Scope: {scope}")
    print(f"  Dry Run: {dry_run}")
    print()
    
    manager = RBACManager(dry_run=dry_run)
    success = True
    
    # Create ServiceAccount
    if not manager.create_service_account(namespace, service_account):
        success = False
    
    if scope == "cluster":
        # Cluster-wide permissions
        role_name = f"{service_account}-role"
        binding_name = f"{service_account}-binding"
        
        if not manager.create_cluster_role(role_name):
            success = False
        
        if not manager.create_cluster_role_binding(
            binding_name,
            service_account,
            namespace,
            role_name
        ):
            success = False
    
    else:  # namespace scope
        # Namespace-scoped permissions
        role_name = f"{service_account}-role"
        binding_name = f"{service_account}-binding"
        
        if not manager.create_role(namespace, role_name):
            success = False
        
        if not manager.create_role_binding(
            namespace,
            binding_name,
            service_account,
            role_name
        ):
            success = False
    
    print("\n" + "="*60)
    if dry_run:
        print("Dry run completed - no resources were actually created")
    elif success:
        print("✓ RBAC setup completed successfully!")
        print("\nNext steps:")
        print(f"  1. Use the service account in your MCP server deployment:")
        print(f"     serviceAccountName: {service_account}")
        print(f"  2. Verify permissions:")
        print(f"     kubectl auth can-i list clusters.postgresql.cnpg.io \\")
        print(f"       --as=system:serviceaccount:{namespace}:{service_account}")
    else:
        print("✗ RBAC setup completed with errors")
        print("\nSome resources may not have been created.")
        print("Check the error messages above for details.")
    print("="*60 + "\n")
    
    return success


def teardown_rbac(
    namespace: str,
    service_account: str,
    scope: str,
    dry_run: bool = False
) -> bool:
    """
    Remove RBAC resources for CloudNativePG MCP server.
    
    Args:
        namespace: Kubernetes namespace of the service account
        service_account: Name of the service account
        scope: Either 'cluster' or 'namespace'
        dry_run: If True, only show what would be deleted
    
    Returns:
        True if all resources were deleted successfully, False otherwise
    """
    print("\n" + "="*60)
    print("CloudNativePG MCP Server - RBAC Teardown")
    print("="*60)
    print(f"\nConfiguration:")
    print(f"  Namespace: {namespace}")
    print(f"  Service Account: {service_account}")
    print(f"  Scope: {scope}")
    print(f"  Dry Run: {dry_run}")
    print()
    
    if not dry_run:
        response = input("Are you sure you want to delete these RBAC resources? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Teardown cancelled.")
            return False
    
    manager = RBACManager(dry_run=dry_run)
    success = True
    
    if scope == "cluster":
        # Delete cluster-wide resources
        role_name = f"{service_account}-role"
        binding_name = f"{service_account}-binding"
        
        if not manager.delete_cluster_role_binding(binding_name):
            success = False
        
        if not manager.delete_cluster_role(role_name):
            success = False
    
    else:  # namespace scope
        # Delete namespace-scoped resources
        role_name = f"{service_account}-role"
        binding_name = f"{service_account}-binding"
        
        if not manager.delete_role_binding(namespace, binding_name):
            success = False
        
        if not manager.delete_role(namespace, role_name):
            success = False
    
    # Delete ServiceAccount
    if not manager.delete_service_account(namespace, service_account):
        success = False
    
    print("\n" + "="*60)
    if dry_run:
        print("Dry run completed - no resources were actually deleted")
    elif success:
        print("✓ RBAC teardown completed successfully!")
    else:
        print("✗ RBAC teardown completed with errors")
    print("="*60 + "\n")
    
    return success


# ============================================================================
# Kubernetes Context Helpers
# ============================================================================

def get_current_namespace() -> str:
    """
    Get the current namespace from the Kubernetes context.
    
    Returns:
        Current namespace from context, or 'default' if not set.
    """
    try:
        # Load the kubeconfig
        contexts, active_context = config.list_kube_config_contexts()
        
        if not active_context:
            return "default"
        
        # Get namespace from active context
        namespace = active_context.get('context', {}).get('namespace')
        
        if namespace:
            return namespace
        
        # If no namespace in context, return default
        return "default"
        
    except Exception:
        # If we can't load config or determine namespace, use default
        return "default"


# ============================================================================
# CLI Entry Point
# ============================================================================

def parse_args():
    """Parse command-line arguments."""
    
    # Get current namespace from context
    current_namespace = get_current_namespace()
    
    parser = argparse.ArgumentParser(
        description="Setup or teardown RBAC resources for CloudNativePG MCP server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Setup with cluster-wide permissions (uses current context namespace)
  python setup_rbac.py
  
  # Setup with explicit namespace
  python setup_rbac.py --namespace production --service-account cnpg-mcp-server
  
  # Setup with namespace-scoped permissions
  python setup_rbac.py --namespace production --service-account cnpg-mcp --scope namespace
  
  # Dry run to see what would be created
  python setup_rbac.py --dry-run
  
  # Delete RBAC resources
  python setup_rbac.py --delete
  
  # Dry run deletion
  python setup_rbac.py --delete --dry-run

Current context namespace: {current_namespace}

Requirements:
  - kubectl must be configured with appropriate permissions
  - For cluster-wide: need cluster-admin or equivalent
  - For namespace-scoped: need admin permissions in the namespace
        """
    )
    
    parser.add_argument(
        "--namespace",
        default=current_namespace,
        help=f"Kubernetes namespace for the service account (default: inferred from context, currently '{current_namespace}')"
    )
    
    parser.add_argument(
        "--service-account",
        default="cnpg-mcp-server",
        help="Name of the service account (default: cnpg-mcp-server)"
    )
    
    parser.add_argument(
        "--scope",
        choices=["cluster", "namespace"],
        default="cluster",
        help="Permission scope: 'cluster' for cluster-wide access or 'namespace' for namespace-scoped (default: cluster)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created/deleted without actually doing it"
    )
    
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete RBAC resources instead of creating them"
    )
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    
    try:
        if args.delete:
            success = teardown_rbac(
                args.namespace,
                args.service_account,
                args.scope,
                args.dry_run
            )
        else:
            success = setup_rbac(
                args.namespace,
                args.service_account,
                args.scope,
                args.dry_run
            )
        
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Fatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
