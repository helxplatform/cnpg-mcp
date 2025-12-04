#!/usr/bin/env python3
"""
Create Kubernetes Secret for MCP JWT Signing Key

Generates a secure 256-bit JWT signing key and stores it in a Kubernetes secret.
This key is used by FastMCP to sign MCP tokens issued to clients.

Requirements:
    pip install kubernetes

Usage:
    # Create secret in current context's namespace
    python create_jwt_secret.py --release-name my-release

    # Create in specific namespace
    python create_jwt_secret.py --namespace mcp --release-name my-release

    # Dry run
    python create_jwt_secret.py --release-name my-release --dry-run

    # Use existing key from file
    python create_jwt_secret.py --release-name my-release --key-file ./jwt-key.txt
"""

import os
import sys
import secrets
import base64
import argparse
from typing import Optional
from pathlib import Path

try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
except ImportError:
    print("❌ kubernetes Python package not installed")
    print("   Install with: pip install kubernetes")
    sys.exit(1)


class JWTSecretCreator:
    """Creates Kubernetes secret for JWT signing key."""

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
                        "created-by": "mcp-jwt-secret-script"
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
        jwt_key: str,
        storage_key: bytes,
        replace: bool = False
    ) -> bool:
        """Create a Kubernetes secret for JWT signing key and storage encryption key."""
        exists = self.secret_exists(name)

        if exists:
            if replace:
                print(f"🔄 Secret {name} exists, replacing...")
                if not self.dry_run:
                    self.delete_secret(name)
            else:
                print(f"⚠️  Secret {name} already exists (use --replace to update)")
                return False

        secret = client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=self.namespace,
                labels={
                    "app": "mcp-server",
                    "component": "jwt-signing-key",
                    "managed-by": "mcp-jwt-secret-script"
                }
            ),
            type="Opaque",
            string_data={
                "jwt-signing-key": jwt_key
            },
            data={
                "storage-encryption-key": base64.b64encode(storage_key).decode()
            }
        )

        if self.dry_run:
            print(f"🔐 [DRY RUN] Would create secret: {name}")
            print(f"   Namespace: {self.namespace}")
            print(f"   Key length: {len(jwt_key)} characters")
            print(f"   Key preview: {jwt_key[:16]}...{jwt_key[-16:]}")
            return True

        try:
            print(f"🔐 Creating secret: {name}")
            self.k8s_client.create_namespaced_secret(
                namespace=self.namespace,
                body=secret
            )
            print(f"✅ Created secret: {name}")
            print(f"   Key: jwt-signing-key")
            return True
        except ApiException as e:
            print(f"❌ Failed to create secret: {e.reason}")
            return False


def generate_jwt_key() -> str:
    """Generate a secure 256-bit JWT signing key."""
    return secrets.token_hex(32)  # 32 bytes = 256 bits


def generate_storage_encryption_key() -> bytes:
    """Generate a secure Fernet encryption key for storage."""
    from cryptography.fernet import Fernet
    return Fernet.generate_key()


def load_jwt_key_from_file(file_path: str) -> str:
    """Load JWT key from file."""
    path = Path(file_path)

    if not path.exists():
        print(f"❌ Key file not found: {file_path}")
        sys.exit(1)

    print(f"📄 Loading key from: {file_path}")

    try:
        jwt_key = path.read_text().strip()

        # Validate key format (should be 64 hex characters for 256-bit key)
        if len(jwt_key) != 64:
            print(f"⚠️  Warning: Key length is {len(jwt_key)} characters, expected 64 for 256-bit key")

        if not all(c in '0123456789abcdefABCDEF' for c in jwt_key):
            print("⚠️  Warning: Key contains non-hexadecimal characters")

        return jwt_key
    except Exception as e:
        print(f"❌ Failed to read key file: {e}")
        sys.exit(1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Create Kubernetes secret for MCP JWT signing key",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate new key and create secret
  python create_jwt_secret.py --release-name my-release

  # Create in specific namespace
  python create_jwt_secret.py --namespace mcp --release-name my-release

  # Dry run
  python create_jwt_secret.py --release-name my-release --dry-run

  # Use existing key from file
  python create_jwt_secret.py --release-name my-release --key-file ./jwt-key.txt

  # Replace existing secret
  python create_jwt_secret.py --release-name my-release --replace

Secret Created:
  <release-name>-jwt-signing-key
     - jwt-signing-key: 256-bit hex key for signing MCP tokens

Key Generation:
  If no key file is provided, a secure random 256-bit key will be generated.
  This key is critical for multi-replica deployments - all replicas must use
  the same key to ensure consistent token validation.

  To generate a key manually:
    python -c "import secrets; print(secrets.token_hex(32))"
        """
    )

    parser.add_argument(
        "--namespace", "-n",
        help="Kubernetes namespace (default: from current context)"
    )
    parser.add_argument(
        "--release-name",
        help="Helm release name (used to generate secret name)",
        required=True
    )
    parser.add_argument(
        "--key-file",
        help="Path to existing JWT key file (default: generate new key)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without creating"
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace secret if it already exists"
    )
    parser.add_argument(
        "--create-namespace",
        action="store_true",
        help="Create namespace if it doesn't exist",
        default=True
    )
    parser.add_argument(
        "--save-key",
        help="Save generated key to file (for backup/reuse)"
    )

    args = parser.parse_args()

    print("=" * 70)
    print("🔐 JWT Signing Key Secret Creator for MCP Server")
    print("=" * 70)
    print()

    creator = JWTSecretCreator(
        namespace=args.namespace,
        dry_run=args.dry_run
    )

    print()

    # Load or generate JWT key
    if args.key_file:
        jwt_key = load_jwt_key_from_file(args.key_file)
        print(f"✅ Loaded existing JWT key from file")
    else:
        print("🔑 Generating new 256-bit JWT signing key...")
        jwt_key = generate_jwt_key()
        print(f"✅ Generated JWT key: {jwt_key[:16]}...{jwt_key[-16:]}")

        # Save key to file if requested
        if args.save_key:
            try:
                save_path = Path(args.save_key)
                save_path.write_text(jwt_key)
                print(f"💾 Saved JWT key to: {args.save_key}")
                print(f"   Keep this file secure - needed for multi-replica deployments")
            except Exception as e:
                print(f"⚠️  Failed to save JWT key to file: {e}")

    # Generate storage encryption key (Fernet)
    print("🔐 Generating Fernet storage encryption key...")
    storage_key = generate_storage_encryption_key()
    print(f"✅ Generated storage key: {storage_key[:16]}...{storage_key[-16:]}")

    print()
    print("=" * 70)
    print("Configuration Summary")
    print("=" * 70)
    print(f"Namespace:        {creator.namespace}")
    print(f"Release Name:     {args.release_name}")
    print(f"Dry Run:          {args.dry_run}")
    print(f"Replace:          {args.replace}")
    print(f"Key Length:       {len(jwt_key)} characters ({len(jwt_key) * 4} bits)")
    print()

    print("Secret to create:")
    print()
    print(f"{args.release_name}-jwt-signing-key")
    print(f"   - jwt-signing-key: {jwt_key[:16]}...{jwt_key[-16:]}")
    print(f"   - storage-encryption-key: {storage_key[:16]}...{storage_key[-16:]}")
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

    # Generate secret name from release name
    secret_name = f"{args.release_name}-jwt-signing-key"

    # Create secret
    success = creator.create_secret(
        name=secret_name,
        jwt_key=jwt_key,
        storage_key=storage_key,
        replace=args.replace
    )

    print()
    print("=" * 70)

    if success:
        print("✅ JWT signing key secret created successfully!")
        print("=" * 70)
        print()
        print("📋 Next Steps:")
        print()
        print("1. Secret created:")
        print(f"   {secret_name}")
        print()
        print("2. Verify secret:")
        print(f"   kubectl describe secret {secret_name} -n {creator.namespace}")
        print()
        print("3. This key will be mounted at:")
        print(f"   /etc/mcp/secrets/jwt-signing-key")
        print()
        if args.save_key:
            print("4. Key backup saved to:")
            print(f"   {args.save_key}")
            print("   Keep this file secure!")
            print()
    else:
        print("❌ Failed to create secret")
        print("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
