#!/usr/bin/env python3
"""
CloudNativePG MCP Server - CNPG Role Binding Script

This script creates a ServiceAccount and binds it to existing CloudNativePG cluster roles
(created by the CloudNativePG helm chart).

The CloudNativePG helm installation creates these roles:
  - cnpg-cloudnative-pg (full admin access)
  - cnpg-cloudnative-pg-edit (edit access - recommended for MCP server)
  - cnpg-cloudnative-pg-view (read-only access)

Usage:
    # Bind to edit role (default)
    python bind_cnpg_role.py --namespace default --service-account cnpg-mcp-server

    # Bind to view role for read-only access
    python bind_cnpg_role.py --namespace default --service-account cnpg-mcp-server --role view

    # Bind to admin role for full access
    python bind_cnpg_role.py --namespace default --service-account cnpg-mcp-server --role admin

    # Dry run to see what would be created
    python bind_cnpg_role.py --dry-run

    # Delete the bindings
    python bind_cnpg_role.py --delete
"""

import argparse
import sys
from typing import Optional, Dict, Any

from kubernetes import client, config
from kubernetes.client.rest import ApiException


# ============================================================================
# CloudNativePG Role Mappings
# ============================================================================

# Map friendly names to actual ClusterRole names created by helm
CNPG_ROLES = {
    "admin": "cnpg-cloudnative-pg",
    "edit": "cnpg-cloudnative-pg-edit",
    "view": "cnpg-cloudnative-pg-view"
}


# ============================================================================
# Resource Management
# ============================================================================

class CNPGRoleBindingManager:
    """Manages role bindings for CloudNativePG MCP server."""

    def __init__(self, dry_run: bool = False):
        """Initialize the role binding manager."""
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

    def verify_cnpg_role_exists(self, role_name: str) -> bool:
        """Verify that a CloudNativePG role exists."""
        try:
            self.rbac_v1.read_cluster_role(role_name)
            return True
        except ApiException as e:
            if e.status == 404:
                return False
            raise

    def list_available_cnpg_roles(self) -> list:
        """List all available CloudNativePG roles."""
        available = []
        try:
            roles = self.rbac_v1.list_cluster_role()
            for role in roles.items:
                if role.metadata.name.startswith("cnpg-cloudnative-pg"):
                    available.append(role.metadata.name)
        except Exception as e:
            print(f"Warning: Could not list roles: {e}", file=sys.stderr)
        return available

    def create_service_account(self, namespace: str, name: str) -> bool:
        """Create a ServiceAccount."""
        try:
            sa = {
                "apiVersion": "v1",
                "kind": "ServiceAccount",
                "metadata": {
                    "name": name,
                    "namespace": namespace,
                    "labels": {
                        "app": "cnpg-mcp-server",
                        "managed-by": "bind-cnpg-role-script"
                    }
                }
            }

            # Check if already exists
            sa_exists = False
            try:
                self.core_v1.read_namespaced_service_account(name, namespace)
                sa_exists = True
            except ApiException as e:
                if e.status != 404:
                    raise

            if sa_exists:
                if self.dry_run:
                    print(f"\n[DRY RUN] ServiceAccount {namespace}/{name} already exists - no action needed")
                else:
                    print(f"✓ ServiceAccount {namespace}/{name} already exists")
                return True

            if self.dry_run:
                print(f"\n[DRY RUN] Would create ServiceAccount: {namespace}/{name}")
                return True

            # Create the ServiceAccount
            self.core_v1.create_namespaced_service_account(namespace, sa)
            print(f"✓ Created ServiceAccount: {namespace}/{name}")
            return True

        except ApiException as e:
            print(f"✗ Failed to create ServiceAccount {namespace}/{name}: {e.reason}", file=sys.stderr)
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
            binding = {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "ClusterRoleBinding",
                "metadata": {
                    "name": name,
                    "labels": {
                        "app": "cnpg-mcp-server",
                        "managed-by": "bind-cnpg-role-script"
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

            if self.dry_run:
                print(f"\n[DRY RUN] Would create ClusterRoleBinding: {name}")
                print(f"  Subject: ServiceAccount {service_account_namespace}/{service_account_name}")
                print(f"  Role: ClusterRole {cluster_role_name}")
                return True

            # Check if already exists
            try:
                existing = self.rbac_v1.read_cluster_role_binding(name)
                print(f"✓ ClusterRoleBinding {name} already exists")
                # Optionally verify it points to the right role
                if existing.role_ref.name != cluster_role_name:
                    print(f"  Warning: Existing binding points to {existing.role_ref.name}, not {cluster_role_name}")
                return True
            except ApiException as e:
                if e.status != 404:
                    raise

            # Create the ClusterRoleBinding
            self.rbac_v1.create_cluster_role_binding(binding)
            print(f"✓ Created ClusterRoleBinding: {name}")
            print(f"  Bound ServiceAccount {service_account_namespace}/{service_account_name} to ClusterRole {cluster_role_name}")
            return True

        except ApiException as e:
            print(f"✗ Failed to create ClusterRoleBinding {name}: {e.reason}", file=sys.stderr)
            if e.status == 403:
                print("  Hint: You need cluster-admin permissions to create ClusterRoleBindings", file=sys.stderr)
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


# ============================================================================
# Main Setup and Teardown Functions
# ============================================================================

def bind_cnpg_role(
    namespace: str,
    service_account: str,
    cnpg_role: str,
    include_view_binding: bool = True,
    dry_run: bool = False
) -> bool:
    """
    Bind a ServiceAccount to CloudNativePG cluster roles.

    Args:
        namespace: Kubernetes namespace for the service account
        service_account: Name of the service account
        cnpg_role: CloudNativePG role level (admin, edit, or view)
        include_view_binding: Also bind to k8s 'view' role for pods/logs/events
        dry_run: If True, only show what would be created

    Returns:
        True if all resources were created successfully, False otherwise
    """
    print("\n" + "="*70)
    print("CloudNativePG MCP Server - Role Binding Setup")
    print("="*70)
    print(f"\nConfiguration:")
    print(f"  Namespace: {namespace}")
    print(f"  Service Account: {service_account}")
    print(f"  CNPG Role: {cnpg_role}")
    print(f"  Include View Binding: {include_view_binding}")
    print(f"  Dry Run: {dry_run}")
    print()

    manager = CNPGRoleBindingManager(dry_run=dry_run)
    success = True

    # Get the actual ClusterRole name
    cnpg_cluster_role = CNPG_ROLES.get(cnpg_role)
    if not cnpg_cluster_role:
        print(f"✗ Invalid CNPG role: {cnpg_role}", file=sys.stderr)
        print(f"  Valid options: {', '.join(CNPG_ROLES.keys())}", file=sys.stderr)
        return False

    # Verify the CloudNativePG role exists
    if not dry_run:
        print(f"Checking if CloudNativePG role '{cnpg_cluster_role}' exists...")
        if not manager.verify_cnpg_role_exists(cnpg_cluster_role):
            print(f"\n✗ CloudNativePG role '{cnpg_cluster_role}' not found!", file=sys.stderr)
            print(f"\nThis usually means CloudNativePG was not installed via helm.", file=sys.stderr)
            print(f"\nAvailable CNPG roles:", file=sys.stderr)
            available = manager.list_available_cnpg_roles()
            if available:
                for role in available:
                    print(f"  - {role}", file=sys.stderr)
            else:
                print(f"  (none found)", file=sys.stderr)
            print(f"\nPlease install CloudNativePG via helm:", file=sys.stderr)
            print(f"  helm install cnpg cloudnative-pg/cloudnative-pg", file=sys.stderr)
            return False
        print(f"✓ CloudNativePG role '{cnpg_cluster_role}' exists\n")

    # Create ServiceAccount
    if not manager.create_service_account(namespace, service_account):
        success = False

    # Create binding to CloudNativePG role
    cnpg_binding_name = f"{service_account}-cnpg-binding"
    if not manager.create_cluster_role_binding(
        cnpg_binding_name,
        service_account,
        namespace,
        cnpg_cluster_role
    ):
        success = False

    # IMPORTANT: The 'edit' role only has write permissions (create, delete, patch, update).
    # We need to also bind to the 'view' role to get read permissions (get, list, watch).
    if cnpg_role == "edit":
        print("Note: 'edit' role only has write permissions. Adding 'view' role for read access...")
        cnpg_view_binding_name = f"{service_account}-cnpg-view-binding"
        if not manager.create_cluster_role_binding(
            cnpg_view_binding_name,
            service_account,
            namespace,
            CNPG_ROLES["view"]  # Also bind to cnpg-cloudnative-pg-view
        ):
            success = False

    # Optionally create binding to k8s view role
    if include_view_binding:
        view_binding_name = f"{service_account}-view-binding"
        if not manager.create_cluster_role_binding(
            view_binding_name,
            service_account,
            namespace,
            "view"  # Built-in Kubernetes role for viewing pods, events, etc.
        ):
            success = False

    print("\n" + "="*70)
    if dry_run:
        print("Dry run completed - no resources were actually created")
    elif success:
        print("✓ Role binding setup completed successfully!")
        print(f"\nServiceAccount '{service_account}' in namespace '{namespace}' now has:")
        if cnpg_role == "edit":
            print(f"  - CloudNativePG {cnpg_role} permissions (write: {cnpg_cluster_role})")
            print(f"  - CloudNativePG view permissions (read: {CNPG_ROLES['view']})")
        else:
            print(f"  - CloudNativePG {cnpg_role} permissions ({cnpg_cluster_role})")
        if include_view_binding:
            print(f"  - Kubernetes view permissions (pods, logs, events)")
        print("\nNext steps:")
        print(f"  1. Use the service account in your MCP server deployment:")
        print(f"     serviceAccountName: {service_account}")
        print(f"  2. Verify permissions:")
        print(f"     kubectl auth can-i get clusters.postgresql.cnpg.io \\")
        print(f"       --as=system:serviceaccount:{namespace}:{service_account}")
        print(f"     kubectl auth can-i create clusters.postgresql.cnpg.io \\")
        print(f"       --as=system:serviceaccount:{namespace}:{service_account}")
    else:
        print("✗ Role binding setup completed with errors")
        print("\nSome resources may not have been created.")
        print("Check the error messages above for details.")
    print("="*70 + "\n")

    return success


def unbind_cnpg_role(
    namespace: str,
    service_account: str,
    include_view_binding: bool = True,
    dry_run: bool = False
) -> bool:
    """
    Remove ServiceAccount and role bindings.

    Args:
        namespace: Kubernetes namespace of the service account
        service_account: Name of the service account
        include_view_binding: Also remove view binding
        dry_run: If True, only show what would be deleted

    Returns:
        True if all resources were deleted successfully, False otherwise
    """
    print("\n" + "="*70)
    print("CloudNativePG MCP Server - Role Binding Teardown")
    print("="*70)
    print(f"\nConfiguration:")
    print(f"  Namespace: {namespace}")
    print(f"  Service Account: {service_account}")
    print(f"  Include View Binding: {include_view_binding}")
    print(f"  Dry Run: {dry_run}")
    print()

    if not dry_run:
        response = input("Are you sure you want to delete these resources? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Teardown cancelled.")
            return False

    manager = CNPGRoleBindingManager(dry_run=dry_run)
    success = True

    # Delete CNPG role binding (edit or admin)
    cnpg_binding_name = f"{service_account}-cnpg-binding"
    if not manager.delete_cluster_role_binding(cnpg_binding_name):
        success = False

    # Delete CNPG view binding (created when using 'edit' role)
    cnpg_view_binding_name = f"{service_account}-cnpg-view-binding"
    if not manager.delete_cluster_role_binding(cnpg_view_binding_name):
        success = False

    # Delete k8s view role binding if it was created
    if include_view_binding:
        view_binding_name = f"{service_account}-view-binding"
        if not manager.delete_cluster_role_binding(view_binding_name):
            success = False

    # Delete ServiceAccount
    if not manager.delete_service_account(namespace, service_account):
        success = False

    print("\n" + "="*70)
    if dry_run:
        print("Dry run completed - no resources were actually deleted")
    elif success:
        print("✓ Role binding teardown completed successfully!")
    else:
        print("✗ Role binding teardown completed with errors")
    print("="*70 + "\n")

    return success


# ============================================================================
# Kubernetes Context Helpers
# ============================================================================

def get_current_namespace() -> str:
    """Get the current namespace from the Kubernetes context."""
    try:
        contexts, active_context = config.list_kube_config_contexts()
        if not active_context:
            return "default"
        namespace = active_context.get('context', {}).get('namespace')
        return namespace if namespace else "default"
    except Exception:
        return "default"


# ============================================================================
# CLI Entry Point
# ============================================================================

def parse_args():
    """Parse command-line arguments."""
    current_namespace = get_current_namespace()

    parser = argparse.ArgumentParser(
        description="Bind CloudNativePG cluster roles to a ServiceAccount for MCP server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Create ServiceAccount and bind to edit role (default)
  python bind_cnpg_role.py --namespace default --service-account cnpg-mcp-server

  # Bind to view role for read-only access
  python bind_cnpg_role.py --namespace default --service-account cnpg-mcp-server --role view

  # Bind to admin role for full access
  python bind_cnpg_role.py --namespace prod --service-account cnpg-admin --role admin

  # Dry run to see what would be created
  python bind_cnpg_role.py --dry-run

  # Skip binding to k8s view role (only bind to CNPG role)
  python bind_cnpg_role.py --no-view-binding

  # Delete bindings and service account
  python bind_cnpg_role.py --delete

CloudNativePG Roles:
  admin - Full administrative access (cnpg-cloudnative-pg)
  edit  - Create, modify, delete clusters (cnpg-cloudnative-pg-edit) [RECOMMENDED]
  view  - Read-only access (cnpg-cloudnative-pg-view)

Current context namespace: {current_namespace}

Requirements:
  - CloudNativePG must be installed via helm (creates the cluster roles)
  - kubectl must be configured with cluster-admin permissions
        """
    )

    parser.add_argument(
        "--namespace",
        default=current_namespace,
        help=f"Kubernetes namespace for the service account (default: {current_namespace})"
    )

    parser.add_argument(
        "--service-account",
        default="cnpg-mcp-server",
        help="Name of the service account to create (default: cnpg-mcp-server)"
    )

    parser.add_argument(
        "--role",
        choices=["admin", "edit", "view"],
        default="edit",
        help="CloudNativePG role level (default: edit)"
    )

    parser.add_argument(
        "--no-view-binding",
        action="store_true",
        help="Don't create binding to k8s 'view' role for pods/logs/events"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created/deleted without actually doing it"
    )

    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete the ServiceAccount and role bindings"
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    try:
        if args.delete:
            success = unbind_cnpg_role(
                args.namespace,
                args.service_account,
                include_view_binding=not args.no_view_binding,
                dry_run=args.dry_run
            )
        else:
            success = bind_cnpg_role(
                args.namespace,
                args.service_account,
                args.role,
                include_view_binding=not args.no_view_binding,
                dry_run=args.dry_run
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
