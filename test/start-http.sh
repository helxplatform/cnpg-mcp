#!/bin/bash
# Start script for CloudNativePG MCP Server in HTTP mode
# Simplifies HTTP mode startup with environment variable validation

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
DEFAULT_HOST="${MCP_HOST:-0.0.0.0}"
DEFAULT_PORT="${MCP_PORT:-4204}"

echo "============================================"
echo "CloudNativePG MCP Server - HTTP Mode"
echo "============================================"
echo ""

# Validate OIDC configuration
if [ -z "$OIDC_ISSUER" ]; then
    echo -e "${YELLOW}WARNING: OIDC_ISSUER not set${NC}"
    echo "The server will run in INSECURE mode (development only)"
    echo "For production, set the following environment variables:"
    echo "  export OIDC_ISSUER=https://your-idp.example.com"
    echo "  export OIDC_AUDIENCE=mcp-api"
    echo ""
    read -p "Continue without OIDC authentication? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Exiting."
        exit 1
    fi
else
    echo -e "${GREEN}✓ OIDC Configuration Found${NC}"
    echo "  Issuer: $OIDC_ISSUER"

    if [ -z "$OIDC_AUDIENCE" ]; then
        echo -e "${RED}ERROR: OIDC_AUDIENCE must be set when OIDC_ISSUER is configured${NC}"
        exit 1
    fi
    echo "  Audience: $OIDC_AUDIENCE"

    if [ -n "$OIDC_JWKS_URI" ]; then
        echo "  JWKS URI: $OIDC_JWKS_URI (override)"
    else
        echo "  JWKS URI: (auto-discover from issuer)"
    fi

    if [ -n "$DCR_PROXY_URL" ]; then
        echo "  DCR Proxy: $DCR_PROXY_URL"
    fi

    echo ""
fi

# Check Kubernetes configuration
echo "Kubernetes Configuration:"
if [ -n "$KUBECONFIG" ]; then
    echo "  KUBECONFIG: $KUBECONFIG"
elif [ -f "$HOME/.kube/config" ]; then
    echo "  Using: $HOME/.kube/config"
elif [ -d "/var/run/secrets/kubernetes.io/serviceaccount" ]; then
    echo "  Using: In-cluster service account"
else
    echo -e "${YELLOW}  WARNING: No Kubernetes config found${NC}"
fi
echo ""

# Display server configuration
echo "Server Configuration:"
echo "  Host: $DEFAULT_HOST"
echo "  Port: $DEFAULT_PORT"
echo "  Transport: HTTP/SSE"
echo ""

# Start the server
echo "Starting server..."
echo "============================================"
echo ""

exec python ../src/cnpg_mcp_server.py \
    --transport http \
    --host "$DEFAULT_HOST" \
    --port "$DEFAULT_PORT"
