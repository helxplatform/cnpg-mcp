#!/usr/bin/env python3
"""
Test Inspector for CloudNativePG MCP Server
Supports both stdio and HTTP transport modes using MCP Inspector

Automatically obtains tokens from auth0-config.json if available.
"""

import os
import sys
import json
import argparse
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, Any

# Colors for terminal output
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color

    @staticmethod
    def red(text): return f"{Colors.RED}{text}{Colors.NC}"
    @staticmethod
    def green(text): return f"{Colors.GREEN}{text}{Colors.NC}"
    @staticmethod
    def yellow(text): return f"{Colors.YELLOW}{text}{Colors.NC}"
    @staticmethod
    def blue(text): return f"{Colors.BLUE}{text}{Colors.NC}"


def check_npx() -> bool:
    """Check if npx is available."""
    return shutil.which("npx") is not None


def load_auth0_config(config_path: str = "auth0-config.json") -> Optional[Dict[str, Any]]:
    """Load Auth0 configuration from file."""
    config_file = Path(config_path)
    if not config_file.exists():
        return None

    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(Colors.yellow(f"Warning: Failed to load {config_path}: {e}"))
        return None


def get_token_from_auth0(config: Dict[str, Any]) -> Optional[str]:
    """
    Attempt to get an access token using management API credentials.

    Args:
        config: Auth0 configuration dictionary

    Returns:
        Access token or None if failed
    """
    try:
        import requests
    except ImportError:
        print(Colors.yellow("Warning: 'requests' library not installed"))
        print("Install with: pip install requests")
        return None

    domain = config.get('domain')
    audience = config.get('audience')

    # Prefer test_client credentials over management_api credentials
    test_client = config.get('test_client', {})
    client_id = test_client.get('client_id')
    client_secret = test_client.get('client_secret')

    # Fallback to management_api (legacy)
    if not client_id or not client_secret:
        print(Colors.yellow("No test_client found, trying management_api (legacy)..."))
        mgmt_api = config.get('management_api', {})
        client_id = mgmt_api.get('client_id')
        client_secret = mgmt_api.get('client_secret')

    if not all([domain, audience, client_id, client_secret]):
        print(Colors.yellow("Warning: Incomplete Auth0 configuration"))
        print("  Missing one or more of: domain, audience, client_id, client_secret")
        print()
        print("To fix this, run:")
        print("  python bin/setup-auth0.py --token YOUR_AUTH0_TOKEN --recreate-client")
        return None

    print(Colors.blue("Attempting to obtain token from Auth0..."))
    print(f"  Domain: {domain}")
    print(f"  Audience: {audience}")
    print(f"  Client ID: {client_id[:20]}...")

    # Try to get token using management client credentials
    token_url = f"https://{domain}/oauth/token"

    try:
        response = requests.post(
            token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "audience": audience
            },
            timeout=10
        )

        if response.status_code == 200:
            token_data = response.json()
            token = token_data.get('access_token')

            if token:
                print(Colors.green("✅ Successfully obtained token from Auth0"))
                print(f"  Token expires in: {token_data.get('expires_in', 'unknown')} seconds")
                return token
            else:
                print(Colors.red("❌ No access_token in response"))
                return None
        else:
            print(Colors.red(f"❌ Failed to get token (HTTP {response.status_code})"))
            try:
                error_data = response.json()
                error = error_data.get('error', 'unknown')
                error_desc = error_data.get('error_description', 'No description')
                print(f"  Error: {error}")
                print(f"  Description: {error_desc}")

                if error == 'access_denied' or 'not authorized' in error_desc.lower():
                    print()
                    print(Colors.yellow("The client is not authorized for the MCP API."))
                    print("This usually means the auth0-config.json is outdated.")
                    print()
                    print("To fix this, re-run the setup script:")
                    print(f"  python bin/setup-auth0.py --token YOUR_AUTH0_TOKEN --recreate-client")
                    print()
                    print("This will create a new test client with proper authorization.")
            except:
                print(f"  Response: {response.text[:200]}")
            return None

    except requests.exceptions.RequestException as e:
        print(Colors.red(f"❌ Network error: {e}"))
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Test the CloudNativePG MCP Server using MCP Inspector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test stdio transport (local development)
  ./test-inspector.py

  # Test HTTP transport (auto-obtains token from auth0-config.json)
  ./test-inspector.py --transport http --url https://cnpg-mcp.wat.im

  # Test HTTP transport with manual token
  ./test-inspector.py --transport http --url https://cnpg-mcp.wat.im --token "eyJ..."

  # Test HTTP transport with token from file
  ./test-inspector.py --transport http --url https://cnpg-mcp.wat.im --token-file token.txt

Environment Variables:
  MCP_HTTP_URL    Default HTTP URL (default: http://localhost:4204)

Notes:
  - Requires npx and @modelcontextprotocol/inspector
  - For stdio mode, the server runs as a subprocess
  - For HTTP mode, automatically checks for auth0-config.json
  - If auth0-config.json exists, attempts to obtain token automatically
  - Manual token via --token or --token-file overrides automatic token
"""
    )

    parser.add_argument(
        '-t', '--transport',
        choices=['stdio', 'http'],
        default='stdio',
        help='Transport mode: stdio (default) or http'
    )
    parser.add_argument(
        '-u', '--url',
        default=os.getenv('MCP_HTTP_URL', 'http://localhost:4204'),
        help='HTTP URL (default: http://localhost:4204 or $MCP_HTTP_URL)'
    )
    parser.add_argument(
        '--token',
        help='JWT bearer token for HTTP mode'
    )
    parser.add_argument(
        '--token-file',
        help='File containing JWT bearer token'
    )
    parser.add_argument(
        '--auth0-config',
        default='auth0-config.json',
        help='Path to auth0-config.json (default: ./auth0-config.json)'
    )

    args = parser.parse_args()

    # Check if npx is available
    if not check_npx():
        print(Colors.red("Error: npx is not installed"))
        print("Please install Node.js and npm to use the MCP Inspector")
        print("Visit: https://nodejs.org/")
        sys.exit(1)

    print("=" * 50)
    print("CloudNativePG MCP Inspector")
    print("=" * 50)
    print()

    # Determine token to use
    token = None
    token_source = None

    # Priority 1: Manual token via --token
    if args.token:
        token = args.token.strip()
        token_source = "command line argument"

    # Priority 2: Token file via --token-file
    elif args.token_file:
        token_file = Path(args.token_file)
        if not token_file.exists():
            print(Colors.red(f"Error: Token file not found: {args.token_file}"))
            sys.exit(1)

        token = token_file.read_text().strip()
        if not token:
            print(Colors.red(f"Error: Token file is empty: {args.token_file}"))
            sys.exit(1)

        token_source = f"file: {args.token_file}"

    # Priority 3: Auto-obtain from auth0-config.json (only for HTTP mode)
    elif args.transport == 'http':
        auth0_config = load_auth0_config(args.auth0_config)

        if auth0_config:
            print(Colors.green(f"✅ Found {args.auth0_config}"))
            print()
            token = get_token_from_auth0(auth0_config)
            if token:
                token_source = f"auto-obtained from {args.auth0_config}"
            else:
                print()
                print(Colors.yellow("⚠️  Could not automatically obtain token"))
                print()
        else:
            print(Colors.yellow(f"⚠️  No {args.auth0_config} found"))
            print()
            print("To enable automatic token retrieval:")
            print(f"1. Run: python bin/setup-auth0.py --token YOUR_AUTH0_MGMT_TOKEN")
            print(f"2. This will create {args.auth0_config} with client credentials")
            print(f"3. The inspector will automatically obtain tokens")
            print()

    # Run inspector based on transport mode
    if args.transport == 'stdio':
        print(f"{Colors.blue('Transport:')} stdio")
        print(f"{Colors.blue('Command:')} python cnpg_mcp_server.py")
        print()
        print(Colors.green("Starting MCP Inspector..."))
        print("The inspector will launch the server as a subprocess.")
        print("Press Ctrl+C to exit.")
        print()

        try:
            subprocess.run(
                ['npx', '@modelcontextprotocol/inspector', 'python', 'cnpg_mcp_server.py'],
                check=True
            )
        except subprocess.CalledProcessError as e:
            print(Colors.red(f"Error: Inspector exited with code {e.returncode}"))
            sys.exit(e.returncode)
        except KeyboardInterrupt:
            print()
            print("Interrupted by user")
            sys.exit(0)

    else:  # HTTP mode
        print(f"{Colors.blue('Transport:')} HTTP")
        print(f"{Colors.blue('URL:')} {args.url}")

        if token:
            print(f"{Colors.blue('Authentication:')} JWT Bearer Token ({token_source})")
            # Show first and last 10 chars of token
            token_preview = f"{token[:10]}...{token[-10:]}"
            print(f"{Colors.blue('Token:')} {token_preview}")
        else:
            print(f"{Colors.yellow('Authentication:')} None (development mode only!)")
            print(f"{Colors.yellow('WARNING:')} No token available. This will only work if OIDC is not configured.")

        print()
        print(Colors.green("Starting MCP Inspector..."))
        print("The inspector will connect to the HTTP endpoint.")
        print("Inspector runs a local proxy that forwards requests to your server.")
        print("Press Ctrl+C to exit.")
        print()

        mcp_endpoint = f"{args.url}/mcp"
        print(f"{Colors.blue('Connecting to:')} {mcp_endpoint}")
        print()

        # Build inspector command
        cmd = [
            'npx', '@modelcontextprotocol/inspector',
            '--transport', 'http',
            '--url', mcp_endpoint
        ]

        if token:
            print(Colors.blue("Passing Authorization header through Inspector proxy..."))
            print()
            cmd.extend(['--header', f'Authorization: Bearer {token}'])

        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(Colors.red(f"Error: Inspector exited with code {e.returncode}"))
            sys.exit(e.returncode)
        except KeyboardInterrupt:
            print()
            print("Interrupted by user")
            sys.exit(0)


if __name__ == "__main__":
    main()
