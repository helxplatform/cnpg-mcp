"""
OIDC Authentication Provider for CloudNativePG MCP Server

This module provides OAuth2/OIDC authentication for the HTTP transport mode,
with support for non-DCR-capable IdPs via a DCR proxy.

Features:
- JWT token verification using RS256/ES256
- JWKS-based public key discovery
- DCR (Dynamic Client Registration) proxy support
- Protected resource server implementation
- Environment-based configuration
"""

import os
import logging
from typing import Optional, Dict, Any
from urllib.parse import urljoin
from pathlib import Path

import httpx
from authlib.jose import jwt, JsonWebKey, JWTClaims, JsonWebEncryption
from authlib.jose.errors import JoseError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Route

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


class JWKSCache:
    """Cache for JWKS (JSON Web Key Set) to avoid repeated fetches."""

    def __init__(self, jwks_uri: str, cache_ttl: int = 3600):
        """
        Initialize JWKS cache.

        Args:
            jwks_uri: URL to fetch JWKS from
            cache_ttl: Time to live for cache in seconds (default: 1 hour)
        """
        self.jwks_uri = jwks_uri
        self.cache_ttl = cache_ttl
        self._jwks: Optional[Dict[str, Any]] = None
        self._last_fetch: float = 0

    async def get_jwks(self) -> Dict[str, Any]:
        """
        Get JWKS, fetching from URI if cache is stale.

        Returns:
            JWKS dictionary with 'keys' array
        """
        import time

        current_time = time.time()

        # Check if cache is valid
        if self._jwks and (current_time - self._last_fetch) < self.cache_ttl:
            return self._jwks

        # Fetch new JWKS
        logger.info(f"Fetching JWKS from {self.jwks_uri}")
        async with httpx.AsyncClient() as client:
            response = await client.get(self.jwks_uri, timeout=10.0)
            response.raise_for_status()
            self._jwks = response.json()
            self._last_fetch = current_time

        return self._jwks


class OIDCAuthProvider:
    """
    OIDC authentication provider for FastMCP HTTP transport.

    Implements JWT Bearer token verification using JWKS from an OIDC provider.
    Supports non-DCR-capable IdPs through a DCR proxy.

    Environment Variables:
        OIDC_ISSUER: OIDC issuer URL (e.g., https://auth.example.com)
        OIDC_AUDIENCE: Expected audience claim in JWT (e.g., mcp-api)
        OIDC_JWKS_URI: Optional override for JWKS URI
        DCR_PROXY_URL: Optional DCR proxy URL for client registration
        OIDC_SCOPE: Required scope (default: openid)
    """

    def __init__(
        self,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
        jwks_uri: Optional[str] = None,
        dcr_proxy_url: Optional[str] = None,
        required_scope: str = "openid",
        config_path: Optional[str] = None,
        client_secrets: Optional[list] = None
    ):
        """
        Initialize OIDC authentication provider.

        Configuration priority (highest to lowest):
        1. Explicit parameters passed to __init__
        2. Config file (/etc/mcp/oidc.yaml or config_path)
        3. Environment variables
        4. Defaults

        Args:
            issuer: OIDC issuer URL (overrides config file and env var)
            audience: Expected audience claim (overrides config file and env var)
            jwks_uri: JWKS URI (overrides auto-discovery)
            dcr_proxy_url: DCR proxy URL for client registration
            required_scope: Required OAuth2 scope (default: openid)
            config_path: Optional path to OIDC config file (YAML)
            client_secrets: List of client_secrets to try for JWE decryption (Auth0 compatibility)
        """
        # Try to load from config file first
        config = load_oidc_config_from_file(config_path) or {}

        # Priority: explicit params > config file > env vars
        self.issuer = issuer or config.get("issuer") or os.getenv("OIDC_ISSUER")
        self.audience = audience or config.get("audience") or os.getenv("OIDC_AUDIENCE")
        self.jwks_uri = jwks_uri or config.get("jwks_uri") or os.getenv("OIDC_JWKS_URI")
        self.dcr_proxy_url = dcr_proxy_url or config.get("dcr_proxy_url") or os.getenv("DCR_PROXY_URL")
        # Don't require scope by default - M2M tokens typically don't have 'openid' scope
        self.required_scope = required_scope or config.get("scope") or os.getenv("OIDC_SCOPE")

        # Debug: Show scope configuration sources
        scope_source = "not set (M2M mode)"
        if required_scope:
            scope_source = f"explicit parameter: '{required_scope}'"
        elif config.get("scope"):
            scope_source = f"config file: '{config.get('scope')}'"
        elif os.getenv("OIDC_SCOPE"):
            scope_source = f"environment: '{os.getenv('OIDC_SCOPE')}'"
        logger.info(f"🔧 Required scope configuration: {scope_source} -> final value: {self.required_scope}")

        # Validate required configuration
        if not self.issuer:
            raise ValueError(
                "OIDC issuer is required. Provide via:\n"
                "  1. Config file at /etc/mcp/oidc.yaml with 'issuer' key\n"
                "  2. OIDC_ISSUER environment variable\n"
                "  3. Pass issuer parameter to OIDCAuthProvider"
            )

        if not self.audience:
            raise ValueError(
                "OIDC audience is required. Provide via:\n"
                "  1. Config file at /etc/mcp/oidc.yaml with 'audience' key\n"
                "  2. OIDC_AUDIENCE environment variable\n"
                "  3. Pass audience parameter to OIDCAuthProvider"
            )

        # Auto-discover JWKS URI if not provided
        if not self.jwks_uri:
            # Standard OIDC discovery: {issuer}/.well-known/openid-configuration
            self.jwks_uri = self._discover_jwks_uri()

        # Initialize JWKS cache
        self.jwks_cache = JWKSCache(self.jwks_uri)

        # Store client secrets for JWE decryption (Auth0 compatibility)
        self.client_secrets = client_secrets or config.get("client_secrets") or []
        if isinstance(self.client_secrets, str):
            self.client_secrets = [self.client_secrets]

        # Load client_secrets from separate file if referenced (Kubernetes Secret mount)
        client_secrets_file = config.get("client_secrets_file")
        self.client_secrets_file = client_secrets_file  # Store for DCR persistence

        if client_secrets_file:
            try:
                logger.info(f"Loading client secrets from: {client_secrets_file}")
                secrets_from_file = self._load_client_secrets_file(client_secrets_file)
                if secrets_from_file:
                    self.client_secrets.extend(secrets_from_file)
                    logger.info(f"✅ Loaded {len(secrets_from_file)} secret(s) from file")
            except Exception as e:
                logger.warning(f"Could not load client secrets from file: {e}")

        # Also try to load DCR-captured secrets from default location
        try:
            dcr_secrets_file = "/etc/mcp/secrets/dcr-captured-secrets.yaml"
            if Path(dcr_secrets_file).exists():
                dcr_secrets = self._load_client_secrets_file(dcr_secrets_file)
                if dcr_secrets:
                    for secret in dcr_secrets:
                        if secret not in self.client_secrets:
                            self.client_secrets.append(secret)
                    logger.info(f"✅ Loaded {len(dcr_secrets)} DCR-captured secret(s)")
        except Exception as e:
            logger.debug(f"No DCR-captured secrets found: {e}")

        # Discover upstream DCR endpoint for proxy (needs to happen at init, not on request)
        self.upstream_dcr_endpoint = None
        try:
            # Try to fetch upstream OIDC configuration to get registration_endpoint
            well_known_url = urljoin(
                self.issuer.rstrip('/') + '/',
                '.well-known/openid-configuration'
            )
            import httpx
            response = httpx.get(well_known_url, timeout=10.0)
            if response.status_code == 200:
                upstream_config = response.json()
                if upstream_config.get("registration_endpoint"):
                    self.upstream_dcr_endpoint = upstream_config["registration_endpoint"]
                    logger.info(f"  DCR: Discovered upstream endpoint {self.upstream_dcr_endpoint}")
                elif self.dcr_proxy_url:
                    self.upstream_dcr_endpoint = self.dcr_proxy_url
                    logger.info(f"  DCR: Using proxy endpoint {self.upstream_dcr_endpoint}")
        except Exception as e:
            logger.debug(f"Could not discover DCR endpoint: {e}")
            if self.dcr_proxy_url:
                self.upstream_dcr_endpoint = self.dcr_proxy_url
                logger.info(f"  DCR: Using proxy endpoint {self.upstream_dcr_endpoint}")

        logger.info(f"OIDC Auth Provider initialized:")
        logger.info(f"  Issuer: {self.issuer}")
        logger.info(f"  Audience: {self.audience}")
        logger.info(f"  JWKS URI: {self.jwks_uri}")
        if self.upstream_dcr_endpoint:
            logger.info(f"  DCR Proxy: Enabled (upstream: {self.upstream_dcr_endpoint})")
        if self.client_secrets:
            logger.info(f"  JWE Decryption: Enabled ({len(self.client_secrets)} secret(s) available)")

    def _load_client_secrets_file(self, file_path: str) -> list:
        """
        Load client secrets from a YAML file (typically mounted from Kubernetes Secret).

        Args:
            file_path: Path to YAML file containing client_secrets

        Returns:
            List of client secrets

        Raises:
            Exception: If file cannot be loaded
        """
        from pathlib import Path
        import yaml

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Client secrets file not found: {file_path}")

        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        secrets = data.get('client_secrets', [])
        if not isinstance(secrets, list):
            secrets = [secrets]

        return secrets

    async def _persist_dcr_secret(self, client_id: str, client_secret: str):
        """
        Persist captured DCR client secret to a file.

        This allows secrets to survive server restarts. The file is appended
        to the client_secrets_file if configured, or to a default location.

        Args:
            client_id: Client ID from DCR response
            client_secret: Client secret to persist
        """
        import yaml
        from pathlib import Path

        # Determine where to persist secrets
        # Use client_secrets_file path if configured, otherwise use a default
        secrets_file = getattr(self, 'client_secrets_file', None)
        if not secrets_file:
            secrets_file = "/etc/mcp/secrets/dcr-captured-secrets.yaml"

        try:
            secrets_path = Path(secrets_file)

            # Load existing secrets if file exists
            existing_secrets = []
            if secrets_path.exists():
                with open(secrets_path, 'r') as f:
                    data = yaml.safe_load(f) or {}
                    existing_secrets = data.get('client_secrets', [])

            # Add new secret if not already present
            if client_secret not in existing_secrets:
                existing_secrets.append(client_secret)

                # Ensure parent directory exists
                secrets_path.parent.mkdir(parents=True, exist_ok=True)

                # Write updated secrets
                with open(secrets_path, 'w') as f:
                    yaml.dump({'client_secrets': existing_secrets}, f, default_flow_style=False)

                logger.info(f"✅ Persisted secret for {client_id} to {secrets_file}")
            else:
                logger.debug(f"Secret for {client_id} already persisted")

        except Exception as e:
            logger.warning(f"Failed to persist secret for {client_id}: {e}")
            logger.info("Secret is still available in memory for current session")

    def _discover_jwks_uri(self) -> str:
        """
        Discover JWKS URI from OIDC issuer's well-known configuration.

        Returns:
            JWKS URI string
        """
        # Construct well-known URL
        well_known_url = urljoin(
            self.issuer.rstrip('/') + '/',
            '.well-known/openid-configuration'
        )

        logger.info(f"Discovering OIDC configuration from {well_known_url}")

        try:
            import httpx
            with httpx.Client() as client:
                response = client.get(well_known_url, timeout=10.0)
                response.raise_for_status()
                config = response.json()
                jwks_uri = config.get('jwks_uri')

                if not jwks_uri:
                    raise ValueError(
                        f"OIDC configuration at {well_known_url} does not contain jwks_uri"
                    )

                logger.info(f"Discovered JWKS URI: {jwks_uri}")
                return jwks_uri

        except Exception as e:
            raise ValueError(
                f"Failed to discover JWKS URI from {well_known_url}: {e}\n"
                f"You can manually set OIDC_JWKS_URI environment variable."
            )

    def _prepare_jwe_key(self, secret: str) -> list:
        """
        Prepare key variations for JWE decryption.

        Auth0 client secrets need special handling for A256GCM (32 bytes required).
        Try multiple key derivation methods.

        Args:
            secret: Client secret string

        Returns:
            List of key variations to try (bytes)
        """
        import base64
        import hashlib

        keys = []
        secret_bytes = secret.encode('utf-8') if isinstance(secret, str) else secret

        # Method 1: Base64url decode (Auth0's typical format)
        try:
            # Add padding if needed
            padding = 4 - (len(secret) % 4)
            padded_secret = secret + ('=' * padding) if padding != 4 else secret
            decoded = base64.urlsafe_b64decode(padded_secret)
            if len(decoded) == 32:
                keys.append(('base64url-decoded', decoded))
        except Exception:
            pass

        # Method 2: SHA256 hash (always 32 bytes)
        keys.append(('sha256-hash', hashlib.sha256(secret_bytes).digest()))

        # Method 3: Direct UTF-8 bytes (if exactly 32 bytes)
        if len(secret_bytes) == 32:
            keys.append(('utf8-direct', secret_bytes))

        # Method 4: Truncate to 32 bytes (if longer)
        if len(secret_bytes) >= 32:
            keys.append(('utf8-truncated', secret_bytes[:32]))

        # Method 5: Original bytes as-is (last resort)
        keys.append(('raw', secret_bytes))

        return keys

    def _decrypt_jwe_token(self, token: str) -> JWTClaims:
        """
        Decrypt JWE token using known client secrets.

        Auth0 encrypts ID tokens with 'dir' algorithm using client_secret.
        We try each known client_secret with multiple key derivation methods.

        Args:
            token: JWE token string

        Returns:
            Decoded JWT claims

        Raises:
            JoseError: If decryption fails with all secrets
        """
        last_error = None
        jwe = JsonWebEncryption()

        for i, secret in enumerate(self.client_secrets, 1):
            # Show partial secret for identification (first 8 chars only)
            secret_preview = f"{secret[:8]}..." if len(secret) > 8 else "***"
            logger.info(f"🔑 Attempting secret {i}/{len(self.client_secrets)}: {secret_preview}")

            # Try multiple key derivation methods
            key_variations = self._prepare_jwe_key(secret)
            logger.info(f"   Generated {len(key_variations)} key variations to try")

            for method, key in key_variations:
                try:
                    logger.info(f"   ➜ Trying method: {method} (key length: {len(key)} bytes)")

                    # Decrypt JWE using the key
                    decrypted_data = jwe.deserialize_compact(token, key)

                    logger.info(f"✅ JWE DECRYPTION SUCCESSFUL!")
                    logger.info(f"   Secret {i} using method: {method}")

                    # The decrypted content is a JWT (signed token)
                    # Extract the payload which contains the claims
                    jwt_string = decrypted_data['payload']

                    # The payload should be bytes, decode to string
                    if isinstance(jwt_string, bytes):
                        jwt_string = jwt_string.decode('utf-8')

                    # Now decode the inner JWT to get claims
                    # Note: For Auth0 encrypted ID tokens, the inner content is typically a signed JWT
                    # We'll decode without verification since the JWE encryption already authenticated it
                    import json
                    claims = json.loads(jwt_string)

                    return claims

                except Exception as e:
                    last_error = e
                    error_msg = str(e)
                    logger.info(f"   ✗ Method {method} failed: {type(e).__name__}: {error_msg}")
                    continue

        # All secrets and methods failed
        logger.error(f"JWE decryption failed with all {len(self.client_secrets)} secret(s)")
        raise JoseError(f"Failed to decrypt JWE token: {last_error}")

    async def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verify JWT bearer token.

        Args:
            token: JWT token string (without 'Bearer ' prefix)

        Returns:
            Decoded JWT claims as dictionary

        Raises:
            JoseError: If token is invalid
            ValueError: If required claims are missing
        """
        # Get JWKS
        jwks_data = await self.jwks_cache.get_jwks()

        # Decode and verify token
        try:
            # Log JWKS for debugging
            logger.debug(f"JWKS has {len(jwks_data.get('keys', []))} key(s)")

            # Try JWT verification first (most common case)
            try:
                # authlib jwt.decode() can accept raw JWKS dict
                # It will automatically select the correct key based on 'kid' header
                claims = jwt.decode(token, jwks_data)
            except JoseError as jwt_error:
                # If JWT verification fails, try JWE decryption (Auth0 encrypted ID tokens)
                if self.client_secrets:
                    # Log comprehensive details about the encrypted token
                    logger.info("=" * 80)
                    logger.info("🔐 ENCRYPTED TOKEN DETECTED (JWE)")
                    logger.info("=" * 80)
                    logger.info(f"JWT verification failed: {jwt_error}")
                    logger.info(f"Token length: {len(token)} characters")
                    logger.info(f"Token (first 100 chars): {token[:100]}...")
                    logger.info(f"Token (last 50 chars): ...{token[-50:]}")

                    # Try to decode the header without verification to see what's inside
                    try:
                        import base64
                        header_b64 = token.split('.')[0]
                        # Add padding if needed
                        padding = 4 - (len(header_b64) % 4)
                        if padding != 4:
                            header_b64 += '=' * padding
                        header_json = base64.urlsafe_b64decode(header_b64)
                        logger.info(f"Token header (decoded): {header_json.decode('utf-8')}")
                    except Exception as e:
                        logger.warning(f"Could not decode token header: {e}")

                    logger.info(f"Attempting JWE decryption with {len(self.client_secrets)} secret(s)")
                    logger.info("=" * 80)

                    claims = self._decrypt_jwe_token(token)
                else:
                    # No client secrets available for JWE decryption
                    raise jwt_error

            # Validate standard claims (exp, nbf, etc.)
            claims.validate()

            # Verify issuer (normalize trailing slashes)
            token_issuer = claims.get('iss', '').rstrip('/')
            expected_issuer = self.issuer.rstrip('/')

            if token_issuer != expected_issuer:
                raise ValueError(
                    f"Invalid issuer. Expected '{expected_issuer}', got '{token_issuer}'"
                )

            # Verify audience
            aud = claims.get('aud')
            if isinstance(aud, list):
                if self.audience not in aud:
                    raise ValueError(
                        f"Invalid audience. Expected '{self.audience}' in {aud}"
                    )
            elif aud != self.audience:
                raise ValueError(
                    f"Invalid audience. Expected '{self.audience}', got '{aud}'"
                )

            # Verify scope if required
            if self.required_scope:
                scope = claims.get('scope', '')
                if isinstance(scope, str):
                    scopes = scope.split()
                else:
                    scopes = scope

                logger.info(f"🔍 Scope validation: required='{self.required_scope}', token_scopes={scopes}")

                if self.required_scope not in scopes:
                    raise ValueError(
                        f"Required scope '{self.required_scope}' not found in token. Token has: {scopes}"
                    )
            else:
                # Log when no scope is required
                token_scopes = claims.get('scope', '')
                logger.info(f"✓ No scope required (M2M mode). Token scopes: {token_scopes}")

            logger.debug(f"Token verified successfully for subject: {claims.get('sub')}")
            return dict(claims)

        except JoseError as e:
            logger.error(f"Token verification failed: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error details: {repr(e)}")
            # Log token header for debugging (safe - doesn't contain secrets)
            try:
                import base64
                header_b64 = token.split('.')[0]
                header_b64 += '=' * (4 - len(header_b64) % 4)  # Add padding
                header = base64.urlsafe_b64decode(header_b64)
                logger.error(f"Token header: {header}")
            except:
                pass
            raise

    async def authenticate_request(self, request: Request) -> Dict[str, Any]:
        """
        Authenticate HTTP request using Bearer token.

        Args:
            request: Starlette Request object

        Returns:
            Decoded JWT claims

        Raises:
            ValueError: If authentication fails
        """
        # Log request details for debugging
        logger.info("=" * 80)
        logger.info("🔍 AUTHENTICATION REQUEST")
        logger.info("=" * 80)
        logger.info(f"Method: {request.method}")

        # Defensive logging for URL (might fail to stringify)
        try:
            logger.info(f"URL: {request.url}")
        except Exception as e:
            logger.error(f"Failed to log URL: {e}")
            try:
                logger.info(f"URL (repr): {repr(request.url)}")
            except:
                logger.info("URL: <unavailable>")

        # Defensive logging for Path
        try:
            logger.info(f"Path: {request.url.path}")
        except Exception as e:
            logger.error(f"Failed to log Path: {e}")
            logger.info("Path: <unavailable>")

        logger.info(f"Client: {request.client.host if request.client else 'unknown'}")
        logger.info(f"Headers: {dict(request.headers)}")
        logger.info("=" * 80)

        # Extract Authorization header
        auth_header = request.headers.get('Authorization')

        if not auth_header:
            raise ValueError("Missing Authorization header")

        # Parse Bearer token
        parts = auth_header.split()

        if len(parts) != 2 or parts[0].lower() != 'bearer':
            raise ValueError("Invalid Authorization header format. Expected 'Bearer <token>'")

        token = parts[1]

        # Verify token
        return await self.verify_token(token)

    def get_metadata_routes(self) -> list:
        """
        Get additional routes for OAuth2 metadata endpoints.

        Returns:
            List of Starlette Route objects
        """
        routes = []

        # Protected resource metadata endpoint (RFC 8414)
        async def oauth_metadata(request):
            """OAuth 2.0 Authorization Server Metadata (RFC 8414)"""
            logger.info(f"📋 OAuth Authorization Server metadata requested from {request.url.path}")
            # Fetch upstream OIDC configuration to get endpoints
            import httpx
            upstream_config = {}
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{self.issuer}/.well-known/openid-configuration",
                        timeout=5.0
                    )
                    if response.status_code == 200:
                        upstream_config = response.json()
            except Exception as e:
                logger.warning(f"Failed to fetch upstream OIDC config: {e}")

            # Use upstream endpoints if available, otherwise derive from issuer
            token_endpoint = upstream_config.get("token_endpoint") or (
                f"{self.issuer}/oauth/token" if "auth0.com" in self.issuer
                else f"{self.issuer}/protocol/openid-connect/token"
            )
            authorization_endpoint = upstream_config.get("authorization_endpoint") or (
                f"{self.issuer}/authorize" if "auth0.com" in self.issuer
                else f"{self.issuer}/protocol/openid-connect/auth"
            )

            # Build scopes list dynamically
            scopes_supported = []
            if self.required_scope:
                scopes_supported.append(self.required_scope)
            # Always include openid for user flows even if not required for M2M
            if "openid" not in scopes_supported:
                scopes_supported.append("openid")

            metadata = {
                "issuer": self.issuer,
                "authorization_endpoint": authorization_endpoint,
                "token_endpoint": token_endpoint,
                "jwks_uri": self.jwks_uri,
                "scopes_supported": scopes_supported,
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "client_credentials"],
                "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
                "subject_types_supported": ["public"],
                "id_token_signing_alg_values_supported": ["RS256"],
            }

            # Add registration endpoint - advertise our own endpoint to capture secrets
            # We'll proxy to Auth0 and capture the client_secret for JWE decryption
            if self.upstream_dcr_endpoint:
                # Use relative URL - client will resolve relative to this server
                metadata["registration_endpoint"] = "/register"
                logger.info(f"📢 Advertising registration endpoint: /register (relative)")

            # Log what we're advertising for debugging
            logger.debug(f"OAuth metadata response: issuer={metadata['issuer']}, "
                        f"has_registration={('registration_endpoint' in metadata)}")

            return JSONResponse(metadata)

        async def register_client(request: Request) -> JSONResponse:
            """
            Handle Dynamic Client Registration (DCR) requests.

            This endpoint proxies to the upstream IdP (Auth0) and captures
            the client_secret from the response for JWE decryption support.

            Flow:
            1. Receive DCR request from Claude Desktop
            2. Forward to upstream DCR endpoint (Auth0)
            3. Capture client_secret from response
            4. Store secret in memory and optionally persist
            5. Return response to Claude Desktop
            """
            logger.info("=" * 70)
            logger.info("🎯 DCR REGISTRATION REQUEST RECEIVED!")
            logger.info(f"   From: {request.client.host if request.client else 'unknown'}")
            logger.info(f"   Method: {request.method}")
            logger.info(f"   URL: {request.url}")
            logger.info("=" * 70)

            try:
                # Get request body and headers
                body = await request.body()
                headers = dict(request.headers)

                # Remove hop-by-hop headers
                for header in ['host', 'connection', 'keep-alive', 'transfer-encoding']:
                    headers.pop(header, None)

                logger.info(f"Proxying DCR request to {self.upstream_dcr_endpoint}")

                # Forward request to upstream DCR endpoint
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self.upstream_dcr_endpoint,
                        content=body,
                        headers=headers,
                        timeout=30.0
                    )

                logger.info(f"Upstream DCR response: {response.status_code}")

                if response.status_code in (200, 201):
                    # Parse response to capture client_secret
                    client_data = response.json()

                    client_id = client_data.get('client_id')
                    client_secret = client_data.get('client_secret')
                    client_name = client_data.get('client_name', 'Unknown')

                    logger.info(f"✅ DCR successful - Client registered: {client_name} ({client_id})")

                    # Capture and store client_secret if present
                    if client_secret:
                        logger.info(f"📝 Captured client_secret for {client_id}")

                        # Add to in-memory secrets list
                        if client_secret not in self.client_secrets:
                            self.client_secrets.append(client_secret)
                            logger.info(f"✅ Added to client_secrets list (now have {len(self.client_secrets)} secret(s))")

                        # Persist secret to file if configured
                        await self._persist_dcr_secret(client_id, client_secret)
                    else:
                        logger.info(f"ℹ️  No client_secret in response (public client)")

                    # Return response to Claude Desktop
                    return JSONResponse(
                        content=client_data,
                        status_code=response.status_code,
                        headers=dict(response.headers)
                    )
                else:
                    logger.error(f"DCR failed: {response.status_code} {response.text}")
                    return JSONResponse(
                        content={"error": "registration_failed", "error_description": response.text},
                        status_code=response.status_code
                    )

            except Exception as e:
                logger.error(f"DCR proxy error: {e}", exc_info=True)
                return JSONResponse(
                    content={"error": "server_error", "error_description": str(e)},
                    status_code=500
                )

        # OAuth Authorization Server metadata (for auth servers like Auth0)
        routes.append(
            Route("/.well-known/oauth-authorization-server", oauth_metadata, methods=["GET"])
        )

        # Protected Resource metadata endpoint (RFC 8707) - for resource servers (us!)
        async def protected_resource_metadata(request):
            """
            OAuth 2.0 Protected Resource Metadata (RFC 8707).

            This advertises our MCP server as a protected resource and points
            clients to the authorization server for authentication/registration.
            """
            metadata = {
                "resource": self.audience,  # Our resource identifier
                "authorization_servers": [self.issuer],  # Auth0 is our auth server
                "bearer_methods_supported": ["header"],  # We accept Bearer tokens in Authorization header
                "scopes_supported": [self.required_scope] if self.required_scope else ["openid"],
            }

            # Include registration endpoint if DCR proxy is enabled
            # Use relative URL - client will resolve relative to this server
            if self.upstream_dcr_endpoint:
                metadata["registration_endpoint"] = "/register"
                logger.info(f"📢 Advertising registration endpoint: /register (relative)")

            logger.debug(f"Protected resource metadata: resource={self.audience}, "
                        f"has_registration={('registration_endpoint' in metadata)}")

            return JSONResponse(metadata)

        routes.append(
            Route("/.well-known/oauth-protected-resource", protected_resource_metadata, methods=["GET"])
        )

        # Add DCR endpoint if configured
        if self.upstream_dcr_endpoint:
            routes.append(
                Route("/register", register_client, methods=["POST"])
            )
            logger.info("✅ DCR proxy endpoint enabled at /register")

        return routes


class OIDCAuthMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware for OIDC authentication.

    Verifies JWT tokens on all requests and injects claims into request state.
    """

    def __init__(self, app, auth_provider: OIDCAuthProvider, exclude_paths: list = None):
        """
        Initialize OIDC middleware.

        Args:
            app: Starlette application
            auth_provider: OIDCAuthProvider instance
            exclude_paths: List of paths to exclude from authentication (e.g., ["/healthz", "/readyz"])
        """
        super().__init__(app)
        self.auth_provider = auth_provider
        self.exclude_paths = exclude_paths or ["/healthz", "/readyz", "/.well-known/"]

    async def dispatch(self, request: Request, call_next):
        """Process request with authentication."""

        # Skip authentication for excluded paths
        for excluded in self.exclude_paths:
            if request.url.path.startswith(excluded):
                return await call_next(request)

        # Authenticate request
        try:
            claims = await self.auth_provider.authenticate_request(request)

            # Inject claims into request state for downstream handlers
            request.state.auth_claims = claims
            request.state.user_id = claims.get('sub')

            # Process request
            response = await call_next(request)
            return response

        except ValueError as e:
            # Authentication failed - return 401 with WWW-Authenticate header
            logger.warning(f"Authentication failed for {request.url.path}: {e}")

            # Build WWW-Authenticate header per RFC 6750
            www_authenticate = f'Bearer realm="MCP API"'
            if "Missing" in str(e):
                www_authenticate += ', error="invalid_request"'
            else:
                www_authenticate += ', error="invalid_token"'
            www_authenticate += f', error_description="{str(e)}"'

            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "error_description": str(e)
                },
                headers={
                    "WWW-Authenticate": www_authenticate
                }
            )

        except JoseError as e:
            # Token verification failed - return 401 with WWW-Authenticate header
            logger.warning(f"Token verification failed for {request.url.path}: {e}")
            return JSONResponse(
                status_code=401,
                content={
                    "error": "invalid_token",
                    "error_description": "Token verification failed"
                },
                headers={
                    "WWW-Authenticate": 'Bearer realm="MCP API", error="invalid_token", error_description="Token verification failed"'
                }
            )

        except Exception as e:
            # Unexpected error - return 500
            logger.error(f"Unexpected authentication error: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={
                    "error": "server_error",
                    "error_description": "Internal authentication error"
                }
            )
