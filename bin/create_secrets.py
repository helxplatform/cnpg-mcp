#!/usr/bin/env python3
"""
Create Kubernetes Secrets for MCP Server

Reads from auth0-config.json (single source of truth) and creates Kubernetes secrets.

Requirements:
    pip install kubernetes

Usage:
    # Create secrets in current context's namespace
    python create_k8s_secrets.py

    # Create in specific namespace
    python create_k8s_secrets.py --namespace mcp

    # Dry run
    python create_k8s_secrets.py --dry-run

    # Specify config file location
    python create_k8s_secrets.py --config-file ./auth0-config.json
"""

import os
import sys
import json
import argparse
import base64
from typing import Dict, Any, Optional

try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
except ImportError:
    print("❌ kubernetes Python package not installed")
    print("   Install with: pip install kubernetes")
    sys.exit(1)


class KubernetesSecretCreator:
    """Creates Kubernetes secrets from Auth0 configuration."""
    
    def __init__(
        self,
        namespace: Optional[str] = None,
        dry_run: bool = False
    ):
        self.dry_run = dry_run
        
        try:
            config.load_kube_config()
            print("✅ Loaded kubeconfig")
        except config.config_exception.ConfigException:
            try:
                config.load_incluster_config()
                print("✅ Loaded in-cluster config")
            except:
                print("❌ Could not load Kubernetes configuration")
                sys.exit(1)
        
        self.k8s_client = client.CoreV1Api()
        
        if namespace:
            self.namespace = namespace
            print(f"📦 Using specified namespace: {self.namespace}")
        else:
            self.namespace = self._get_current_namespace()
            print(f"📦 Using namespace from context: {self.namespace}")
        
        try:
            self.k8s_client.get_api_resources()
            print(f"✅ Connected to Kubernetes cluster")
        except Exception as e:
            print(f"❌ Could not connect to Kubernetes cluster: {e}")
            sys.exit(1)
    
    def _get_current_namespace(self) -> str:
        """Get the current namespace from kubectl context."""
        try:
            _, active_context = config.list_kube_config_contexts()
            
            if active_context and 'context' in active_context:
                context = active_context['context']
                namespace = context.get('namespace', 'default')
                return namespace
            
            return 'default'
        except Exception:
            return 'default'
    
    def load_config(self, config_file: str) -> Dict[str, Any]:
        """Load configuration from auth0-config.json."""
        if not os.path.exists(config_file):
            print(f"❌ Configuration file not found: {config_file}")
            print("\nRun the setup script first:")
            print("  python setup_auth0_for_mcp.py")
            sys.exit(1)
        
        print(f"📄 Loading {config_file}...")
        
        try:
            with open(config_file, 'r') as f:
                config_data = json.load(f)
                print(f"   Loaded configuration successfully")
                return config_data
        except Exception as e:
            print(f"❌ Failed to load config file: {e}")
            sys.exit(1)
    
    def namespace_exists(self) -> bool:
        """Check if the namespace exists."""
        try:
            self.k8s_client.read_namespace(self.namespace)
            return True
        except ApiException as e:
            if e.status == 404:
                return False
            raise
    
    def create_namespace(self) -> bool:
        """Create namespace if it doesn't exist."""
        if self.namespace == "default":
            return True
        
        if self.namespace_exists():
            print(f"✅ Namespace {self.namespace} exists")
            return True
        
        print(f"📦 Creating namespace: {self.namespace}")
        
        if self.dry_run:
            print(f"   [DRY RUN] Would create namespace: {self.namespace}")
            return True
        
        try:
            namespace = client.V1Namespace(
                metadata=client.V1ObjectMeta(
                    name=self.namespace,
                    labels={
                        "name": self.namespace,
                        "created-by": "mcp-setup-script"
                    }
                )
            )
            self.k8s_client.create_namespace(namespace)
            print(f"✅ Created namespace: {self.namespace}")
            return True
        except ApiException as e:
            print(f"❌ Failed to create namespace: {e.reason}")
            return False
    
    def secret_exists(self, name: str) -> bool:
        """Check if a secret exists."""
        try:
            self.k8s_client.read_namespaced_secret(name, self.namespace)
            return True
        except ApiException as e:
            if e.status == 404:
                return False
            raise
    
    def delete_secret(self, name: str) -> bool:
        """Delete a secret."""
        try:
            self.k8s_client.delete_namespaced_secret(
                name=name,
                namespace=self.namespace,
                body=client.V1DeleteOptions()
            )
            return True
        except ApiException:
            return False
    
    def create_secret(
        self,
        name: str,
        data: Dict[str, str],
        labels: Optional[Dict[str, str]] = None,
        replace: bool = False
    ) -> bool:
        """Create a Kubernetes secret."""
        exists = self.secret_exists(name)
        
        if exists:
            if replace:
                print(f"🔄 Secret {name} exists, replacing...")
                if not self.dry_run:
                    self.delete_secret(name)
            else:
                print(f"⚠️  Secret {name} already exists (use --replace to update)")
                return False
        
        encoded_data = {
            k: base64.b64encode(v.encode()).decode()
            for k, v in data.items()
        }
        
        final_labels = {
            "app": "mcp-server",
            "managed-by": "mcp-setup-script"
        }
        if labels:
            final_labels.update(labels)
        
        secret = client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=self.namespace,
                labels=final_labels
            ),
            type="Opaque",
            data=encoded_data
        )
        
        if self.dry_run:
            print(f"🔐 [DRY RUN] Would create secret: {name}")
            print(f"   Namespace: {self.namespace}")
            print(f"   Data keys: {', '.join(data.keys())}")
            return True
        
        try:
            print(f"🔐 Creating secret: {name}")
            self.k8s_client.create_namespaced_secret(
                namespace=self.namespace,
                body=secret
            )
            print(f"✅ Created secret: {name}")
            print(f"   Keys: {', '.join(data.keys())}")
            return True
        except ApiException as e:
            print(f"❌ Failed to create secret: {e.reason}")
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Create Kubernetes secrets from auth0-config.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create secrets in current context's namespace
  python create_k8s_secrets.py

  # Create in specific namespace
  python create_k8s_secrets.py --namespace mcp

  # Dry run
  python create_k8s_secrets.py --dry-run

  # Replace existing secrets
  python create_k8s_secrets.py --replace

  # Specify config file location
  python create_k8s_secrets.py --config-file ./config/auth0-config.json

Secrets Created:
  1. mcp-auth0-config
     - AUTH0_ISSUER
     - AUTH0_AUDIENCE
     
  2. mcp-auth0-mgmt (Management API credentials)
     - client-id
     - client-secret
     - domain
     - connection-id
        """
    )
    
    parser.add_argument(
        "--namespace", "-n",
        help="Kubernetes namespace (default: from current context)"
    )
    parser.add_argument(
        "--config-file",
        help="Path to auth0-config.json file (default: ./auth0-config.json)",
        default="./auth0-config.json"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without creating"
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace secrets if they already exist"
    )
    parser.add_argument(
        "--create-namespace",
        action="store_true",
        help="Create namespace if it doesn't exist",
        default=True
    )
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("🔐 Kubernetes Secret Creator for MCP Server")
    print("=" * 70)
    print()
    
    creator = KubernetesSecretCreator(
        namespace=args.namespace,
        dry_run=args.dry_run
    )
    
    print()
    
    # Load configuration from auth0-config.json
    auth_config = creator.load_config(args.config_file)
    
    # Validate configuration
    required_keys = ['domain', 'issuer', 'audience', 'management_api', 'connection_id']
    missing = [key for key in required_keys if key not in auth_config]
    
    if missing:
        print(f"❌ Missing required configuration: {', '.join(missing)}")
        print("\nRun the setup script first:")
        print("  python setup_auth0_for_mcp.py")
        sys.exit(1)
    
    mgmt_api = auth_config.get('management_api', {})
    if not mgmt_api.get('client_secret'):
        print("\n⚠️  Warning: Management client secret is empty")
        print("   Run setup script with --recreate-client:")
        print("   python setup_auth0_for_mcp.py --token YOUR_TOKEN --recreate-client")
        
        proceed = input("\nContinue anyway? (y/N): ")
        if proceed.lower() != 'y':
            print("Aborted.")
            sys.exit(0)
    
    print()
    print("=" * 70)
    print("Configuration Summary")
    print("=" * 70)
    print(f"Namespace:        {creator.namespace}")
    print(f"Dry Run:          {args.dry_run}")
    print(f"Replace:          {args.replace}")
    print()
    
    # Prepare secret data
    config_data = {
        'AUTH0_ISSUER': auth_config['issuer'],
        'AUTH0_AUDIENCE': auth_config['audience']
    }
    
    mgmt_data = {
        'client-id': mgmt_api.get('client_id', ''),
        'client-secret': mgmt_api.get('client_secret', ''),
        'domain': auth_config['domain'],
        'connection-id': auth_config['connection_id']
    }
    
    print("Secrets to create:")
    print()
    print("1. mcp-auth0-config")
    for key, value in config_data.items():
        print(f"   - {key}: {value}")
    print()
    
    print("2. mcp-auth0-mgmt")
    for key, value in mgmt_data.items():
        if 'secret' in key.lower():
            display = "***hidden***" if value else "***empty***"
            print(f"   - {key}: {display}")
        else:
            print(f"   - {key}: {value}")
    print()
    
    if not args.dry_run:
        proceed = input("Proceed with secret creation? (y/N): ")
        if proceed.lower() != 'y':
            print("Aborted.")
            sys.exit(0)
    
    print()
    
    if args.create_namespace:
        if not creator.create_namespace():
            sys.exit(1)
        print()
    
    success = True
    
    # Create secrets
    if not creator.create_secret(
        name="mcp-auth0-config",
        data=config_data,
        labels={"component": "auth0-config"},
        replace=args.replace
    ):
        success = False
    print()
    
    if not creator.create_secret(
        name="mcp-auth0-mgmt",
        data=mgmt_data,
        labels={"component": "auth0-management"},
        replace=args.replace
    ):
        success = False
    print()
    
    print("=" * 70)
    
    if success:
        print("✅ All secrets created successfully!")
        print("=" * 70)
        print()
        print("📋 Next Steps:")
        print()
        print("1. Deploy your MCP server:")
        print(f"   helm upgrade --install mcp-server ./mcp-server-chart -n {creator.namespace}")
        print()
        print("2. Verify secrets:")
        print(f"   kubectl get secrets -n {creator.namespace}")
        print(f"   kubectl describe secret mcp-auth0-config -n {creator.namespace}")
        print()
    else:
        print("❌ Some secrets failed to create")
        print("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
