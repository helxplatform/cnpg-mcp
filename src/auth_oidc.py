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
from authlib.jose import jwt, JsonWebKey, JWTClaims
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
        config_path: Optional[str] = None
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

        logger.info(f"OIDC Auth Provider initialized:")
        logger.info(f"  Issuer: {self.issuer}")
        logger.info(f"  Audience: {self.audience}")
        logger.info(f"  JWKS URI: {self.jwks_uri}")
        if self.dcr_proxy_url:
            logger.info(f"  DCR Proxy: {self.dcr_proxy_url}")

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
        jwks = await self.jwks_cache.get_jwks()

        # Decode and verify token
        try:
            # authlib will automatically select the correct key based on 'kid' header
            claims = jwt.decode(token, jwks)

            # Validate standard claims
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
            logger.warning(f"Token verification failed: {e}")
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

            # Add registration endpoint from upstream config or DCR proxy
            if upstream_config.get("registration_endpoint"):
                # Use native DCR from IdP (Auth0, Keycloak, etc.)
                metadata["registration_endpoint"] = upstream_config["registration_endpoint"]
            elif self.dcr_proxy_url:
                # Use DCR proxy for IdPs without native DCR support
                metadata["registration_endpoint"] = self.dcr_proxy_url

            return JSONResponse(metadata)

        routes.append(
            Route("/.well-known/oauth-authorization-server", oauth_metadata, methods=["GET"])
        )

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
