"""
User identification utilities for CloudNativePG MCP Server.

Provides functions to create Kubernetes-compatible user identifiers from
JWT token claims (preferred_username and issuer).
"""

import hashlib
import re
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(ALPHABET)  # 62


def short_hash(s: str, length: int = 6) -> str:
    """
    Generate a short, alphanumeric hash of a string.

    Uses SHA-256 and base-62 encoding to create a fixed-length hash.

    Args:
        s: Input string to hash
        length: Length of the output hash (default: 6)

    Returns:
        A fixed-length alphanumeric string (0-9, A-Z, a-z)

    Examples:
        >>> short_hash("https://issuer.example.com")
        'kZ8F2b'
    """
    # 1. Strong hash of the input
    digest = hashlib.sha256(s.encode("utf-8")).digest()

    # 2. Turn hash bytes into an integer and clamp it into 62**length range
    num = int.from_bytes(digest, "big") % (BASE ** length)

    # 3. Convert to base-62 with fixed length
    chars = []
    for _ in range(length):
        num, rem = divmod(num, BASE)
        chars.append(ALPHABET[rem])

    return "".join(chars)  # 6-char alphanumeric string


def sanitize_username(username: str) -> str:
    """
    Sanitize a username to be RFC 1123 DNS label compatible.

    Converts to lowercase, replaces invalid characters with hyphens,
    and ensures it starts and ends with alphanumeric characters.

    Args:
        username: Raw username from JWT token

    Returns:
        RFC 1123 compatible username

    Examples:
        >>> sanitize_username("John.Doe@example.com")
        'john-doe'
        >>> sanitize_username("user_name")
        'user-name'
    """
    if not username:
        return "user"

    # Convert to lowercase
    username = username.lower()

    # Extract email local part if it's an email
    if "@" in username:
        username = username.split("@")[0]

    # Replace invalid characters with hyphens
    username = re.sub(r'[^a-z0-9-]', '-', username)

    # Remove leading/trailing hyphens
    username = username.strip('-')

    # Collapse multiple consecutive hyphens
    username = re.sub(r'-+', '-', username)

    # Ensure it starts with alphanumeric
    username = re.sub(r'^[^a-z0-9]+', '', username)

    # Ensure it ends with alphanumeric
    username = re.sub(r'[^a-z0-9]+$', '', username)

    # If empty after sanitization, return default
    if not username:
        return "user"

    # Limit to 50 characters to leave room for hash suffix
    return username[:50]


def generate_user_id(preferred_username: str, issuer: str) -> str:
    """
    Generate a unique user identifier from JWT claims.

    Combines the preferred username with a short hash of the issuer
    to create a unique, RFC 1123 DNS label compatible identifier.

    Format: <sanitized-username>-<6-char-hash-of-issuer>

    Args:
        preferred_username: User's preferred name from JWT token
        issuer: Issuer (iss) from JWT token

    Returns:
        RFC 1123 compatible user ID (max 63 chars)

    Examples:
        >>> generate_user_id("john.doe", "https://auth.example.com")
        'john-doe-kZ8F2b'
        >>> generate_user_id("alice@example.com", "https://auth.example.com")
        'alice-kZ8F2b'
    """
    # Sanitize the username
    sanitized = sanitize_username(preferred_username)

    # Generate hash of issuer
    issuer_hash = short_hash(issuer, length=6)

    # Combine with hyphen
    user_id = f"{sanitized}-{issuer_hash}"

    # Ensure total length doesn't exceed 63 characters
    if len(user_id) > 63:
        # Truncate username part to fit within 63 chars
        max_username_len = 63 - 7  # 7 = len("-") + len(issuer_hash)
        sanitized = sanitized[:max_username_len]
        user_id = f"{sanitized}-{issuer_hash}"

    logger.debug(f"Generated user ID: {user_id} (from {preferred_username} @ {issuer})")

    return user_id


def extract_user_info_from_request(request: Any) -> Optional[Dict[str, str]]:
    """
    Extract user information from FastMCP/Starlette request.

    Looks for JWT claims in request.state or request.user.

    Args:
        request: Starlette Request object from FastMCP

    Returns:
        Dict with 'preferred_username', 'issuer', and 'user_id' if found, None otherwise

    Example:
        >>> info = extract_user_info_from_request(request)
        >>> if info:
        ...     print(f"User: {info['user_id']}")
    """
    try:
        # Try request.user first (common Starlette pattern)
        # Note: request.user is a property that may raise if AuthenticationMiddleware not installed
        user = None
        claims = None
        try:
            user = request.user
            if user and hasattr(user, 'claims'):
                claims = user.claims
            elif user and isinstance(user, dict):
                claims = user
        except (AttributeError, RuntimeError, AssertionError):
            # AuthenticationMiddleware not installed or request.user not available
            # Starlette raises AssertionError: "AuthenticationMiddleware must be installed..."
            pass

        # Try request.state.user if we didn't find claims yet
        if not claims and hasattr(request, 'state') and hasattr(request.state, 'user'):
            user = request.state.user
            if hasattr(user, 'claims'):
                claims = user.claims
            elif isinstance(user, dict):
                claims = user

        # Try request.state.claims if still no claims
        if not claims and hasattr(request, 'state') and hasattr(request.state, 'claims'):
            claims = request.state.claims

        if not claims:
            logger.debug("No user claims found in request")
            return None

        # Extract preferred_username (try multiple claim names)
        preferred_username = (
            claims.get('preferred_username') or
            claims.get('username') or
            claims.get('name') or
            claims.get('email') or
            claims.get('sub')
        )

        # Extract issuer
        issuer = claims.get('iss')

        if not preferred_username or not issuer:
            logger.warning(f"Missing required claims: preferred_username={preferred_username}, iss={issuer}")
            return None

        # Generate unique user ID
        user_id = generate_user_id(preferred_username, issuer)

        return {
            'preferred_username': preferred_username,
            'issuer': issuer,
            'user_id': user_id
        }

    except Exception as e:
        logger.error(f"Error extracting user info from request: {e}")
        return None
