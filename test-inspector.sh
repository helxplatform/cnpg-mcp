#!/bin/bash
# Test Inspector for CloudNativePG MCP Server
# Supports both stdio and HTTP transport modes using MCP Inspector

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
TRANSPORT="stdio"
HTTP_URL="${MCP_HTTP_URL:-http://localhost:4204}"
TOKEN=""
TOKEN_FILE=""

# Show usage
usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Test the CloudNativePG MCP Server using MCP Inspector

OPTIONS:
    -t, --transport <mode>    Transport mode: stdio (default) or http
    -u, --url <url>          HTTP URL (default: http://localhost:4204)
    --token <token>          JWT bearer token for HTTP mode
    --token-file <file>      File containing JWT bearer token
    -h, --help               Show this help message

EXAMPLES:
    # Test stdio transport (local development)
    $0

    # Test stdio transport explicitly
    $0 --transport stdio

    # Test HTTP transport (no auth - development only)
    $0 --transport http --url http://localhost:4204

    # Test HTTP transport with authentication
    $0 --transport http --url https://cnpg-mcp.wat.im --token "eyJ..."

    # Test HTTP transport with token from file
    $0 --transport http --url https://cnpg-mcp.wat.im --token-file token.txt

    # Test HTTP transport using environment variable for URL
    export MCP_HTTP_URL=https://cnpg-mcp.wat.im
    $0 --transport http --token-file token.txt

ENVIRONMENT VARIABLES:
    MCP_HTTP_URL             Default HTTP URL (default: http://localhost:4204)

NOTES:
    - Requires npx and @modelcontextprotocol/inspector
    - For stdio mode, the server runs as a subprocess
    - For HTTP mode with OIDC, you must provide a valid JWT token
    - Inspector runs a local proxy that forwards requests to your server

EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -t|--transport)
            TRANSPORT="$2"
            shift 2
            ;;
        -u|--url)
            HTTP_URL="$2"
            shift 2
            ;;
        --token)
            TOKEN="$2"
            shift 2
            ;;
        --token-file)
            TOKEN_FILE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo -e "${RED}Error: Unknown option: $1${NC}"
            echo "Run '$0 --help' for usage information"
            exit 1
            ;;
    esac
done

# Validate transport mode
if [[ "$TRANSPORT" != "stdio" && "$TRANSPORT" != "http" ]]; then
    echo -e "${RED}Error: Invalid transport mode '$TRANSPORT'${NC}"
    echo "Valid options: stdio, http"
    exit 1
fi

# Load token from file if specified
if [[ -n "$TOKEN_FILE" ]]; then
    if [[ ! -f "$TOKEN_FILE" ]]; then
        echo -e "${RED}Error: Token file not found: $TOKEN_FILE${NC}"
        exit 1
    fi
    TOKEN=$(cat "$TOKEN_FILE" | tr -d '\n' | tr -d ' ')
    if [[ -z "$TOKEN" ]]; then
        echo -e "${RED}Error: Token file is empty: $TOKEN_FILE${NC}"
        exit 1
    fi
fi

# Check if npx is available
if ! command -v npx &> /dev/null; then
    echo -e "${RED}Error: npx is not installed${NC}"
    echo "Please install Node.js and npm to use the MCP Inspector"
    echo "Visit: https://nodejs.org/"
    exit 1
fi

echo "============================================"
echo "CloudNativePG MCP Inspector"
echo "============================================"
echo ""

# Run inspector based on transport mode
if [[ "$TRANSPORT" == "stdio" ]]; then
    echo -e "${BLUE}Transport:${NC} stdio"
    echo -e "${BLUE}Command:${NC} python cnpg_mcp_server.py"
    echo ""
    echo -e "${GREEN}Starting MCP Inspector...${NC}"
    echo "The inspector will launch the server as a subprocess."
    echo "Press Ctrl+C to exit."
    echo ""

    # Run inspector with stdio transport
    npx @modelcontextprotocol/inspector python cnpg_mcp_server.py

elif [[ "$TRANSPORT" == "http" ]]; then
    echo -e "${BLUE}Transport:${NC} HTTP"
    echo -e "${BLUE}URL:${NC} $HTTP_URL"

    if [[ -n "$TOKEN" ]]; then
        echo -e "${BLUE}Authentication:${NC} JWT Bearer Token (provided)"
        # Show first and last 10 chars of token
        TOKEN_PREFIX="${TOKEN:0:10}"
        TOKEN_SUFFIX="${TOKEN: -10}"
        echo -e "${BLUE}Token:${NC} ${TOKEN_PREFIX}...${TOKEN_SUFFIX}"
    else
        echo -e "${YELLOW}Authentication:${NC} None (development mode only!)"
        echo -e "${YELLOW}WARNING:${NC} No token provided. This will only work if OIDC is not configured."
    fi

    echo ""
    echo -e "${GREEN}Starting MCP Inspector...${NC}"
    echo "The inspector will connect to the HTTP endpoint."
    echo "Inspector runs a local proxy that forwards requests to your server."
    echo "Press Ctrl+C to exit."
    echo ""

    # MCP Inspector expects the full URL including protocol
    MCP_ENDPOINT="${HTTP_URL}/mcp"

    echo -e "${BLUE}Connecting to:${NC} $MCP_ENDPOINT"
    echo ""

    # Build inspector command with proper header handling
    if [[ -n "$TOKEN" ]]; then
        # Inspector expects headers in this format for HTTP transport
        # The -H flag passes headers through the proxy to the backend
        echo -e "${BLUE}Passing Authorization header through Inspector proxy...${NC}"
        echo ""
        npx @modelcontextprotocol/inspector \
            --transport http \
            --url "$MCP_ENDPOINT" \
            --header "Authorization: Bearer $TOKEN"
    else
        # Without authentication
        npx @modelcontextprotocol/inspector \
            --transport http \
            --url "$MCP_ENDPOINT"
    fi
fi
