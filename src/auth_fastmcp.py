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
import secrets
from typing import Optional, Dict, Any
from pathlib import Path

from fastmcp.server.auth.providers.auth0 import Auth0Provider

# Redis storage backend for OAuth session persistence
try:
    from key_value.aio.stores.redis import RedisStore
    from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
    from cryptography.fernet import Fernet
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    RedisStore = None
    FernetEncryptionWrapper = None
    Fernet = None

# Configure logging
logger = logging.getLogger(__name__)

# Enable DEBUG logging if DEBUG environment variable is set
if os.getenv("DEBUG", "").lower() in ("true", "1", "yes"):
    logger.setLevel(logging.DEBUG)
    # Also set root logger to DEBUG
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.debug("🐛 DEBUG logging enabled for auth_fastmcp module")
else:
    # Default to INFO level
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


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
    logger.debug("=== OIDC Config File Loading ===")

    search_paths = []

    if config_path:
        search_paths.append(config_path)

    # Standard Kubernetes ConfigMap/Secret mount paths
    search_paths.extend([
        "/etc/mcp/oidc.yaml",
        "/config/oidc.yaml",
        "./oidc.yaml"
    ])

    logger.debug(f"Searching for config in paths: {search_paths}")

    for path_str in search_paths:
        path = Path(path_str)
        logger.debug(f"Checking: {path}")
        logger.debug(f"  Exists: {path.exists()}")
        if path.exists():
            logger.debug(f"  Is file: {path.is_file()}")

        if path.exists() and path.is_file():
            try:
                logger.info(f"📄 Loading OIDC config from: {path}")

                with open(path, 'r') as f:
                    try:
                        import yaml
                        config = yaml.safe_load(f)
                        logger.info(f"✅ Successfully loaded OIDC config from {path}")
                        logger.debug(f"   Config keys found: {list(config.keys())}")

                        # Log some non-sensitive config values
                        if 'redis' in config:
                            logger.debug(f"   Redis config present: {list(config['redis'].keys())}")
                        if 'jwt_signing_key_file' in config:
                            logger.debug(f"   JWT signing key file configured: {config['jwt_signing_key_file']}")

                        return config
                    except ImportError:
                        logger.error("❌ PyYAML not installed. Install with: pip install pyyaml")
                        raise

            except Exception as e:
                logger.warning(f"⚠️  Failed to load config from {path}: {e}")
                logger.warning(f"   Error type: {type(e).__name__}")
                continue

    logger.warning("⚠️  No OIDC config file found in any search path")
    logger.warning("   Will attempt to use environment variables")
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


def load_jwt_signing_key(config: Dict[str, Any]) -> str:
    """
    Load JWT signing key for MCP token signing.

    Priority:
    1. jwt_signing_key_file (path to key file)
    2. jwt_signing_key (direct value)
    3. Environment variable JWT_SIGNING_KEY
    4. Generate a random key (WARNING: not suitable for production with multiple replicas)

    Args:
        config: OIDC configuration dictionary

    Returns:
        JWT signing key string (256-bit hex)

    Note:
        For production deployments with multiple replicas, you MUST provide
        a consistent signing key via file, config, or environment variable.
        Generated keys are only valid for single-replica deployments.
    """
    logger.debug("=== JWT Signing Key Loading ===")

    # Try file-based key first (Kubernetes Secret mount)
    key_file = config.get("jwt_signing_key_file")
    logger.debug(f"jwt_signing_key_file from config: {key_file}")

    if key_file:
        try:
            key_path = Path(key_file)
            logger.debug(f"Checking if key file exists: {key_path}")
            logger.debug(f"File exists: {key_path.exists()}")
            if key_path.exists():
                key = key_path.read_text().strip()
                logger.info(f"✅ Loaded JWT signing key from file: {key_file}")
                logger.debug(f"   Key length: {len(key)} characters")
                logger.debug(f"   Key preview: {key[:16]}...{key[-16:]}")
                return key
            else:
                logger.warning(f"⚠️  JWT signing key file not found: {key_file}")
        except Exception as e:
            logger.error(f"❌ Could not load JWT signing key from file: {e}")
            logger.error(f"   Error type: {type(e).__name__}")

    # Try direct config value or environment
    key_in_config = config.get("jwt_signing_key")
    key_in_env = os.getenv("JWT_SIGNING_KEY")
    logger.debug(f"jwt_signing_key in config: {'***set***' if key_in_config else 'not set'}")
    logger.debug(f"JWT_SIGNING_KEY env var: {'***set***' if key_in_env else 'not set'}")

    key = key_in_config or key_in_env
    if key:
        logger.info("✅ Loaded JWT signing key from config/environment")
        logger.debug(f"   Key length: {len(key)} characters")
        return key

    # Generate random key (WARNING: not production-safe for multi-replica)
    logger.warning("⚠️  ⚠️  ⚠️  WARNING: No JWT signing key provided!")
    logger.warning("⚠️  Generating random key - NOT suitable for production!")
    logger.warning("⚠️  Tokens will become INVALID after pod restarts!")
    logger.warning("⚠️  Set jwt_signing_key_file, jwt_signing_key, or JWT_SIGNING_KEY")
    random_key = secrets.token_hex(32)  # 256-bit key
    logger.info(f"Generated random JWT signing key: {random_key[:8]}...")
    return random_key


def create_redis_client_storage(config: Dict[str, Any]):
    """
    Create Redis client storage for OAuth token persistence.

    Configuration (priority order):
    1. Config file redis section
    2. Environment variables (REDIS_URL or REDIS_HOST/PORT/DB/PASSWORD)

    Args:
        config: OIDC configuration dictionary

    Returns:
        RedisClientStorage instance or None if Redis not configured/available

    Required config:
    - redis.url: Full Redis URL (redis://host:port/db)
      OR
    - redis.host: Redis hostname (default: localhost)
    - redis.port: Redis port (default: 6379)
    - redis.db: Redis database number (default: 0)
    - redis.password: Redis password (optional)
    """
    logger.debug("=== Redis Client Storage Initialization ===")

    if not REDIS_AVAILABLE:
        logger.warning("⚠️  Redis storage not available - install py-key-value-aio[redis]")
        logger.warning("⚠️  OAuth sessions will not persist across restarts")
        return None

    redis_config = config.get("redis", {})
    logger.debug(f"Redis config from file: {redis_config}")

    # Extract Redis connection parameters
    host = redis_config.get("host") or os.getenv("REDIS_HOST", "localhost")
    port = redis_config.get("port") or int(os.getenv("REDIS_PORT", "6379"))
    db = redis_config.get("db") or int(os.getenv("REDIS_DB", "0"))
    password = redis_config.get("password") or os.getenv("REDIS_PASSWORD")

    logger.debug(f"Redis connection parameters:")
    logger.debug(f"  Host: {host}")
    logger.debug(f"  Port: {port}")
    logger.debug(f"  DB: {db}")
    logger.debug(f"  Password: {'***set***' if password else 'not set'}")

    try:
        logger.info(f"🔌 Connecting to Redis: {host}:{port}/{db}")

        # Create Redis store
        redis_store = RedisStore(
            host=host,
            port=port,
            db=db,
            password=password if password else None
        )

        # Get Fernet encryption key for OAuth token encryption
        # Priority: 1. File path from config, 2. Direct value from config, 3. Generate random
        encryption_key_file = config.get("storage_encryption_key_file")
        encryption_key = None

        if encryption_key_file:
            try:
                key_path = Path(encryption_key_file)
                logger.debug(f"Checking encryption key file: {key_path}")
                if key_path.exists():
                    encryption_key = key_path.read_bytes()
                    logger.info(f"✅ Loaded storage encryption key from: {encryption_key_file}")
                else:
                    logger.warning(f"⚠️  Storage encryption key file not found: {encryption_key_file}")
            except Exception as e:
                logger.error(f"❌ Could not load encryption key from file: {e}")

        if not encryption_key:
            encryption_key = config.get("storage_encryption_key")
            if encryption_key:
                logger.info("✅ Loaded storage encryption key from config")
                # Ensure key is bytes
                if isinstance(encryption_key, str):
                    encryption_key = encryption_key.encode()

        if not encryption_key:
            logger.warning("⚠️  ⚠️  ⚠️  WARNING: No storage encryption key provided!")
            logger.warning("⚠️  Generating random key - NOT suitable for production!")
            logger.warning("⚠️  Tokens will become INVALID after pod restarts!")
            logger.warning("⚠️  Set storage_encryption_key_file or storage_encryption_key in config")
            encryption_key = Fernet.generate_key()

        logger.debug(f"Encryption key length: {len(encryption_key)} bytes")

        # Wrap Redis store with encryption for OAuth token security
        client_storage = FernetEncryptionWrapper(
            key_value=redis_store,
            fernet=Fernet(encryption_key)
        )

        logger.info("✅ Redis client storage configured successfully")
        logger.info("   OAuth tokens encrypted with Fernet")
        logger.info("   Sessions will persist across restarts")

        return client_storage

    except Exception as e:
        logger.error(f"❌ Failed to create Redis storage: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
        logger.error(f"   Error details: {str(e)}")
        logger.warning("⚠️  OAuth sessions will not persist across restarts")
        return None


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
    logger.info("=" * 70)
    logger.info("🔐 Initializing FastMCP Auth0 Provider")
    logger.info("=" * 70)

    # Load configuration
    config = load_oidc_config_from_file(config_path) or {}
    logger.debug(f"Loaded config keys: {list(config.keys())}")

    # Extract required parameters
    issuer = config.get("issuer") or os.getenv("OIDC_ISSUER")
    audience = config.get("audience") or os.getenv("OIDC_AUDIENCE")
    client_id = config.get("client_id") or os.getenv("AUTH0_CLIENT_ID")
    public_url = config.get("public_url") or os.getenv("PUBLIC_URL")

    logger.debug(f"Configuration extracted:")
    logger.debug(f"  issuer: {issuer}")
    logger.debug(f"  audience: {audience}")
    logger.debug(f"  client_id: {client_id}")
    logger.debug(f"  public_url: {public_url}")

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

    # Load JWT signing key (required for multi-replica deployments)
    jwt_signing_key = load_jwt_signing_key(config)

    # Create Redis client storage (optional but recommended for production)
    client_storage = create_redis_client_storage(config)

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
    logger.info(f"  JWT Signing: {'Custom key' if 'JWT_SIGNING_KEY' in os.environ or config.get('jwt_signing_key') else 'Generated (single-replica only)'}")
    logger.info(f"  Client Storage: {'Redis (persistent)' if client_storage else 'In-memory (not persistent)'}")

    # Create Auth0 Provider with optional client storage and JWT signing key
    # This is a specialized provider for Auth0 that handles OIDC configuration automatically
    provider_kwargs = {
        "config_url": config_url,
        "client_id": client_id,
        "client_secret": client_secret,
        "audience": audience,
        "base_url": public_url,
        "redirect_path": "/auth/callback",
        "require_authorization_consent": True,
        "jwt_signing_key": jwt_signing_key,
    }

    # Only add client_storage if it was successfully created
    if client_storage:
        provider_kwargs["client_storage"] = client_storage

    logger.debug("Creating Auth0Provider with kwargs:")
    for key, value in provider_kwargs.items():
        if key in ['client_secret', 'jwt_signing_key']:
            logger.debug(f"  {key}: ***hidden***")
        elif key == 'client_storage':
            logger.debug(f"  {key}: {type(value).__name__}")
        else:
            logger.debug(f"  {key}: {value}")

    auth_provider = Auth0Provider(**provider_kwargs)

    logger.info("=" * 70)
    logger.info("✅ FastMCP Auth0 Provider configured successfully")
    logger.info("=" * 70)
    logger.info("Token Configuration:")
    logger.info("  • Issuance: MCP server issues its own JWT tokens")
    logger.info("  • Auth0 tokens: Stored securely (encrypted with Fernet)")
    logger.info("  • Client tokens: Signed with HS256, validated by MCP server")
    logger.info("  • JWT Signing Key: " + ("Custom key" if jwt_signing_key else "Generated"))
    logger.info("")
    logger.info("Session Persistence:")
    if client_storage:
        logger.info("  • ✅ ENABLED via Redis")
        logger.info("  • OAuth sessions will persist across restarts")
        logger.info("  • Tokens will remain valid after pod restarts")
    else:
        logger.warning("  • ⚠️  DISABLED - using in-memory storage")
        logger.warning("  • OAuth sessions will be LOST on restart")
        logger.warning("  • Tokens will become INVALID after pod restarts")
    logger.info("=" * 70)

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
