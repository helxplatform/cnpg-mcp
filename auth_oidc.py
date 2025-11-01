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

import httpx
from authlib.jose import jwt, JsonWebKey, JWTClaims
from authlib.jose.errors import JoseError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Route

# Configure logging
logger = logging.getLogger(__name__)


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
        required_scope: str = "openid"
    ):
        """
        Initialize OIDC authentication provider.

        Args:
            issuer: OIDC issuer URL (overrides env var)
            audience: Expected audience claim (overrides env var)
            jwks_uri: JWKS URI (overrides auto-discovery)
            dcr_proxy_url: DCR proxy URL for client registration
            required_scope: Required OAuth2 scope (default: openid)
        """
        # Load from environment or use provided values
        self.issuer = issuer or os.getenv("OIDC_ISSUER")
        self.audience = audience or os.getenv("OIDC_AUDIENCE")
        self.jwks_uri = jwks_uri or os.getenv("OIDC_JWKS_URI")
        self.dcr_proxy_url = dcr_proxy_url or os.getenv("DCR_PROXY_URL")
        self.required_scope = required_scope or os.getenv("OIDC_SCOPE", "openid")

        # Validate required configuration
        if not self.issuer:
            raise ValueError(
                "OIDC issuer is required. Set OIDC_ISSUER environment variable "
                "or pass issuer parameter."
            )

        if not self.audience:
            raise ValueError(
                "OIDC audience is required. Set OIDC_AUDIENCE environment variable "
                "or pass audience parameter."
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

            # Verify issuer
            if claims.get('iss') != self.issuer:
                raise ValueError(
                    f"Invalid issuer. Expected '{self.issuer}', got '{claims.get('iss')}'"
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

                if self.required_scope not in scopes:
                    raise ValueError(
                        f"Required scope '{self.required_scope}' not found in token"
                    )

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
            metadata = {
                "issuer": self.issuer,
                "jwks_uri": self.jwks_uri,
                "scopes_supported": [self.required_scope, "openid"],
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "client_credentials"],
                "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
            }

            # Add DCR proxy registration endpoint if configured
            if self.dcr_proxy_url:
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
            # Authentication failed - return 401
            logger.warning(f"Authentication failed for {request.url.path}: {e}")
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "error_description": str(e)
                }
            )

        except JoseError as e:
            # Token verification failed - return 401
            logger.warning(f"Token verification failed for {request.url.path}: {e}")
            return JSONResponse(
                status_code=401,
                content={
                    "error": "invalid_token",
                    "error_description": "Token verification failed"
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
