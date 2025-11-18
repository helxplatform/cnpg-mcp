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
import time
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

  # Test HTTP with auth proxy (EASIEST! Full UI, zero copy-paste! 🎉)
  ./test-inspector.py --transport http --url https://cnpg-mcp.wat.im --use-proxy

  # Test HTTP with kubectl port-forward (for testing in-cluster deployment)
  ./test-inspector.py --transport http --port-forward --namespace claude

  # Test HTTP direct with CLI mode (text output, automatic auth header)
  ./test-inspector.py --transport http --url https://cnpg-mcp.wat.im --cli

  # Test HTTP direct with UI mode (requires manual header setup)
  ./test-inspector.py --transport http --url https://cnpg-mcp.wat.im

  # Custom proxy port
  ./test-inspector.py --transport http --url https://cnpg-mcp.wat.im --use-proxy --proxy-port 9000

Testing Modes:
  stdio           - Local server as subprocess (no auth)
  http direct     - Connect to remote HTTPS server (manual auth in UI)
  http --use-proxy - Auto-start auth proxy (ZERO copy-paste, full UI!)
  http --port-forward - Use kubectl to access in-cluster service
  http --cli      - CLI mode with automatic auth header

Environment Variables:
  MCP_HTTP_URL    Default HTTP URL (default: http://localhost:4204)

Notes:
  - Requires npx and @modelcontextprotocol/inspector
  - For stdio mode, the server runs as a subprocess
  - For HTTP --use-proxy: Full UI with automatic auth (RECOMMENDED!)
  - For HTTP --cli: Text output with automatic auth header
  - For HTTP direct: Web UI but requires manual header configuration
  - For HTTP --port-forward: kubectl must be configured for the cluster
  - Automatically obtains user token from tmp/user-token.txt (run ./test/get-user-token.py first)
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
    parser.add_argument(
        '--cli',
        action='store_true',
        help='Use Inspector CLI mode (no copy-paste needed for auth!)'
    )
    parser.add_argument(
        '--method',
        default='tools/list',
        help='CLI method to call (default: tools/list)'
    )
    parser.add_argument(
        '--use-proxy',
        action='store_true',
        help='Start local auth proxy automatically (eliminates copy-paste in UI mode!)'
    )
    parser.add_argument(
        '--proxy-port',
        type=int,
        default=8889,
        help='Auth proxy port (default: 8889)'
    )
    parser.add_argument(
        '--port-forward',
        action='store_true',
        help='Use kubectl port-forward to access MCP server in cluster'
    )
    parser.add_argument(
        '--namespace',
        default='claude',
        help='Kubernetes namespace for port-forward (default: claude)'
    )
    parser.add_argument(
        '--service',
        default='cnpg-mcp-cnpg-mcp',
        help='Kubernetes service name for port-forward (default: cnpg-mcp-cnpg-mcp)'
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

    # Priority 3: Auto-obtain from auth0-config.json or tmp/user-token.txt (only for HTTP mode)
    elif args.transport == 'http':
        # For CLI mode, prefer user token (has openid scope)
        # For UI mode, M2M token is fine since user will configure headers manually

        if args.cli:
            # CLI mode requires user token with openid scope
            user_token_file = Path("tmp/user-token.txt")

            if user_token_file.exists():
                token = user_token_file.read_text().strip()
                token_source = "tmp/user-token.txt (user authentication)"
                print(Colors.green(f"✅ Using user token from {user_token_file}"))
                print()
            else:
                print(Colors.yellow(f"⚠️  No user token found"))
                print()
                print("CLI mode requires user authentication (with 'openid' scope).")
                print()
                print("To get a user token, run:")
                print("  ./test/get-user-token.py")
                print()
                print("Then try again:")
                print(f"  {' '.join(sys.argv)}")
                print()
                sys.exit(1)
        else:
            # UI mode - try to get M2M token (user will configure headers manually)
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
        print(f"{Colors.blue('Command:')} python src/cnpg_mcp_server.py")
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

        # Track background processes for cleanup
        background_processes = []

        try:
            # Determine connection mode and URL
            if args.port_forward:
                # Mode 1: kubectl port-forward
                print(f"{Colors.blue('Mode:')} kubectl port-forward")
                print(f"{Colors.blue('Namespace:')} {args.namespace}")
                print(f"{Colors.blue('Service:')} {args.service}")
                print()

                # Start kubectl port-forward
                print(Colors.green("Starting kubectl port-forward..."))
                forward_port = 4204
                port_forward_cmd = [
                    'kubectl', 'port-forward',
                    '-n', args.namespace,
                    f'svc/{args.service}',
                    f'{forward_port}:4204'
                ]

                port_forward_proc = subprocess.Popen(
                    port_forward_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                background_processes.append(('kubectl port-forward', port_forward_proc))

                # Wait a moment for port-forward to establish
                time.sleep(2)

                mcp_endpoint = f"http://localhost:{forward_port}/mcp"
                print(f"✅ Port-forward established")
                print()

            elif args.use_proxy:
                # Mode 2: Local auth proxy
                print(f"{Colors.blue('Mode:')} Auth proxy (auto-injects headers)")
                print(f"{Colors.blue('Backend:')} {args.url}")
                print(f"{Colors.blue('Proxy port:')} {args.proxy_port}")
                print()

                if not token:
                    print(Colors.red("Error: --use-proxy requires a token"))
                    print("Run ./test/get-user-token.py first, or provide --token/--token-file")
                    sys.exit(1)

                # Start auth proxy
                print(Colors.green("Starting auth proxy..."))
                proxy_cmd = [
                    sys.executable,  # Use same Python interpreter
                    './test/mcp-auth-proxy.py',
                    '--backend', args.url,
                    '--port', str(args.proxy_port),
                    '--token-file', 'tmp/user-token.txt'
                ]

                proxy_proc = subprocess.Popen(
                    proxy_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT
                )
                background_processes.append(('auth proxy', proxy_proc))

                # Wait a moment for proxy to start
                time.sleep(2)

                mcp_endpoint = f"http://localhost:{args.proxy_port}/mcp"
                print(f"✅ Auth proxy running at http://localhost:{args.proxy_port}")
                print(f"   (Automatically adds Authorization header)")
                print()

            else:
                # Mode 3: Direct connection
                print(f"{Colors.blue('Mode:')} Direct connection")
                print(f"{Colors.blue('URL:')} {args.url}")
                print()

                if token:
                    print(f"{Colors.blue('Authentication:')} JWT Bearer Token ({token_source})")
                    token_preview = f"{token[:10]}...{token[-10:]}"
                    print(f"{Colors.blue('Token:')} {token_preview}")
                else:
                    print(f"{Colors.yellow('Authentication:')} None (development mode only!)")
                    print(f"{Colors.yellow('WARNING:')} No token available. This will only work if OIDC is not configured.")
                print()

                mcp_endpoint = f"{args.url}/mcp"

            print(Colors.green("Starting MCP Inspector..."))
            print("The inspector will connect to the HTTP endpoint.")
            print("Press Ctrl+C to exit.")
            print()
            print(f"{Colors.blue('Connecting to:')} {mcp_endpoint}")
            print()

            # Determine Inspector command based on mode
            if args.cli:
                # CLI mode - automatic header injection
                print(Colors.green("Using CLI mode with automatic authentication"))
                print()

                if not token and not args.use_proxy:
                    print(Colors.red("Error: CLI mode requires authentication token"))
                    print("Run with --token or --token-file, or use stdio transport")
                    sys.exit(1)

                # Build inspector command for CLI mode
                cmd = [
                    'npx', '@modelcontextprotocol/inspector',
                    '--cli',
                    mcp_endpoint,
                    '--transport', 'http',
                    '--method', args.method,
                ]

                # Only add auth header if not using proxy (proxy handles auth)
                if not args.use_proxy and token:
                    cmd.extend(['--header', f'Authorization: Bearer {token}'])

                print(Colors.blue(f"Method: {args.method}"))
                print()
                print(Colors.green("No copy-paste needed! Header injected automatically."))
                print()

            else:
                # UI mode
                if not args.use_proxy:
                    # Direct connection or port-forward - may need manual header
                    if token:
                        token_file = Path("inspector-token.txt")
                        token_file.write_text(token)
                        print(Colors.green(f"✅ Token saved to: {token_file}"))
                        print()

                        if not args.port_forward:
                            # Direct connection needs manual setup
                            print(Colors.yellow("NOTE: Inspector UI mode requires manual header configuration."))
                            print()
                            print("To connect with authentication:")
                            print(f"1. The inspector will open in your browser")
                            print(f"2. In the connection dialog, enter URL: {mcp_endpoint}")
                            print(f"3. Click 'Advanced' or 'Headers'")
                            print(f"4. Add header:")
                            print(f"   - Name: Authorization")
                            print(f"   - Value: Bearer {token[:20]}...{token[-20:]}")
                            print()
                            print("OR copy the full token from inspector-token.txt")
                            print()
                            print(Colors.blue("💡 TIP: Use --use-proxy to skip copy-paste!"))
                            print(f"   ./test-inspector.py --transport http --url {args.url} --use-proxy")
                            print()
                else:
                    # Using proxy - no manual configuration needed!
                    print(Colors.green("✅ No auth configuration needed!"))
                    print("   The proxy automatically adds the Authorization header")
                    print()

                if not args.use_proxy and not args.port_forward:
                    input("Press Enter to launch inspector...")
                    print()

                # Build inspector command for UI mode
                cmd = [
                    'npx', '@modelcontextprotocol/inspector',
                    '--transport', 'http',
                    '--url', mcp_endpoint
                ]

            # Run inspector
            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as e:
                print(Colors.red(f"Error: Inspector exited with code {e.returncode}"))
                sys.exit(e.returncode)
            except KeyboardInterrupt:
                print()
                print("Interrupted by user")

        finally:
            # Cleanup background processes
            for name, proc in background_processes:
                print()
                print(Colors.yellow(f"Stopping {name}..."))
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                    print(f"✅ {name} stopped")
                except subprocess.TimeoutExpired:
                    proc.kill()
                    print(f"⚠️  {name} killed")


if __name__ == "__main__":
    main()
