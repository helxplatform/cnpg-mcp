"""
FastMCP OAuth Proxy Configuration for CloudNativePG MCP Server

This module configures FastMCP's built-in OAuth Proxy for Auth0 integration.
The proxy handles token issuance properly: it receives Auth0 tokens internally
and issues its own MCP JWT tokens to clients, solving the JWE token problem.

Key Features:
- Uses FastMCP's OAuthProxy (built-in, production-ready)
- Issues MCP-signed JWT tokens (not Auth0's JWE tokens)
- Encrypts and stores Auth0 tokens securely
- Handles DCR proxy transparently
- Validates tokens properly with audience boundaries
"""

import os
import logging
from typing import Optional, Dict, Any
from pathlib import Path

from fastmcp.server.auth.providers.auth0 import Auth0Provider

# Configure logging
logger = logging.getLogger(__name__)


def load_oidc_config_from_file(config_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Load OIDC configuration from a YAML file.

    Searches in order:
    1. Provided config_path
    2. /etc/mcp/oidc.yaml (default Kubernetes ConfigMap mount)
    3. /config/oidc.yaml
    4. ./oidc.yaml

    Args:
        config_path: Optional explicit path to config file

    Returns:
        Dict with OIDC config or None if no file found
    """
    search_paths = []

    if config_path:
        search_paths.append(config_path)

    # Standard Kubernetes ConfigMap/Secret mount paths
    search_paths.extend([
        "/etc/mcp/oidc.yaml",
        "/config/oidc.yaml",
        "./oidc.yaml"
    ])

    for path_str in search_paths:
        path = Path(path_str)
        if path.exists() and path.is_file():
            try:
                logger.info(f"Loading OIDC config from: {path}")

                with open(path, 'r') as f:
                    try:
                        import yaml
                        config = yaml.safe_load(f)
                        logger.info(f"✓ Successfully loaded OIDC config from {path}")
                        return config
                    except ImportError:
                        logger.error("PyYAML not installed. Install with: pip install pyyaml")
                        raise

            except Exception as e:
                logger.warning(f"Failed to load config from {path}: {e}")
                continue

    logger.debug("No OIDC config file found, will use environment variables")
    return None


def load_client_secret(config: Dict[str, Any]) -> str:
    """
    Load client secret from file or config.

    Priority:
    1. client_secret_file (path to secret file)
    2. client_secret (direct value)
    3. Environment variable AUTH0_CLIENT_SECRET

    Args:
        config: OIDC configuration dictionary

    Returns:
        Client secret string

    Raises:
        ValueError: If no client secret found
    """
    # Try file-based secret first (Kubernetes Secret mount)
    client_secret_file = config.get("client_secret_file")
    if client_secret_file:
        try:
            secret_path = Path(client_secret_file)
            if secret_path.exists():
                client_secret = secret_path.read_text().strip()
                logger.info(f"✅ Loaded client secret from: {client_secret_file}")
                return client_secret
            else:
                logger.warning(f"Client secret file not found: {client_secret_file}")
        except Exception as e:
            logger.warning(f"Could not load client secret from file: {e}")

    # Try direct config value
    client_secret = config.get("client_secret") or os.getenv("AUTH0_CLIENT_SECRET")
    if client_secret:
        logger.info("✅ Loaded client secret from config/environment")
        return client_secret

    raise ValueError("No client secret found. Set client_secret_file, client_secret, or AUTH0_CLIENT_SECRET")


def create_auth0_oauth_proxy(config_path: Optional[str] = None) -> Auth0Provider:
    """
    Create and configure FastMCP OAuth Proxy for Auth0.

    This function creates a properly configured OAuth Proxy that:
    1. Receives authorization codes from Auth0
    2. Exchanges them for Auth0 tokens (may be JWE encrypted)
    3. Stores Auth0 tokens securely (encrypted with Fernet)
    4. Issues its own JWT tokens to MCP clients (signed with HS256)
    5. Validates client tokens and looks up stored Auth0 sessions

    Configuration is loaded from (priority order):
    1. Config file (YAML) at /etc/mcp/oidc.yaml or config_path
    2. Environment variables
    3. Defaults

    Required configuration:
    - issuer: Auth0 domain (e.g., https://your-domain.auth0.com)
    - audience: API identifier (e.g., https://your-api.example.com/mcp)
    - client_id: Auth0 application client ID
    - client_secret: Auth0 application client secret (or client_secret_file)
    - public_url: Public URL of this MCP server (for OAuth callbacks)

    Args:
        config_path: Optional path to OIDC config file

    Returns:
        Configured OAuthProxy instance

    Raises:
        ValueError: If required configuration is missing
    """
    # Load configuration
    config = load_oidc_config_from_file(config_path) or {}

    # Extract required parameters
    issuer = config.get("issuer") or os.getenv("OIDC_ISSUER")
    audience = config.get("audience") or os.getenv("OIDC_AUDIENCE")
    client_id = config.get("client_id") or os.getenv("AUTH0_CLIENT_ID")
    public_url = config.get("public_url") or os.getenv("PUBLIC_URL")

    # Validate required parameters
    if not issuer:
        raise ValueError("OIDC issuer is required. Set 'issuer' in config file or OIDC_ISSUER environment variable")
    if not audience:
        raise ValueError("OIDC audience is required. Set 'audience' in config file or OIDC_AUDIENCE environment variable")
    if not client_id:
        raise ValueError("Auth0 client ID is required. Set 'client_id' in config file or AUTH0_CLIENT_ID environment variable")
    if not public_url:
        raise ValueError("Public URL is required. Set 'public_url' in config file or PUBLIC_URL environment variable")

    # Load client secret (may be from file)
    client_secret = load_client_secret(config)

    # Normalize issuer (remove trailing slash for consistency)
    issuer = issuer.rstrip('/')

    # Construct OIDC configuration URL
    config_url = f"{issuer}/.well-known/openid-configuration"

    logger.info("Configuring FastMCP Auth0 Provider:")
    logger.info(f"  Issuer: {issuer}")
    logger.info(f"  Config URL: {config_url}")
    logger.info(f"  Audience: {audience}")
    logger.info(f"  Client ID: {client_id}")
    logger.info(f"  Public URL: {public_url}")

    # Create Auth0 Provider
    # This is a specialized provider for Auth0 that handles OIDC configuration automatically
    auth_provider = Auth0Provider(
        config_url=config_url,
        client_id=client_id,
        client_secret=client_secret,
        audience=audience,
        base_url=public_url,
        redirect_path="/auth/callback",
        require_authorization_consent=True
    )

    logger.info("✅ FastMCP Auth0 Provider configured successfully")
    logger.info("   Token issuance: MCP server will issue its own JWT tokens")
    logger.info("   Auth0 tokens: Stored securely (encrypted with Fernet)")
    logger.info("   Client tokens: Signed with HS256, validated by MCP server")

    return auth_provider


def get_auth_config_summary(issuer: str, audience: str, client_id: str, public_url: str) -> Dict[str, Any]:
    """
    Get summary of OAuth Proxy configuration for logging/debugging.

    Args:
        issuer: Auth0 issuer URL
        audience: API audience
        client_id: Auth0 client ID
        public_url: Public URL of MCP server

    Returns:
        Dictionary with configuration summary
    """
    return {
        "provider": "Auth0",
        "issuer": issuer,
        "audience": audience,
        "client_id": client_id,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "public_url": public_url,
        "redirect_path": "/auth/callback",
        "pkce_enabled": True,
        "consent_required": True
    }
