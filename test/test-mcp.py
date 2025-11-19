#!/usr/bin/env python3
"""
CloudNativePG MCP Server Test Runner

Primary testing tool with two modes:
1. Automated tests via plugin system (default)
2. Interactive Inspector UI (--use-inspector flag)

Automatically obtains tokens from auth0-config.json if available.
"""

import os
import sys
import json
import argparse
import subprocess
import shutil
import time
import asyncio
import importlib
import inspect
from pathlib import Path
from typing import Optional, Dict, Any, List

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


def get_user_token_interactive() -> Optional[str]:
    """
    Get user token by running get-user-token.py script.

    This will open a browser for Auth0 login and return the token.

    Returns:
        Access token or None if failed
    """
    print()
    print("=" * 70)
    print(Colors.blue("🔐 USER AUTHENTICATION REQUIRED"))
    print("=" * 70)
    print()
    print("The MCP server requires the 'openid' scope, which needs user login.")
    print("Running get-user-token.py to authenticate...")
    print()

    # Run get-user-token.py
    script_path = Path(__file__).parent / "get-user-token.py"

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=False,  # Let it interact with user
            text=True
        )

        if result.returncode != 0:
            print()
            print(Colors.red("❌ User authentication failed"))
            return None

        # Token should be saved to /tmp/user-token.txt
        token_file = Path("/tmp/user-token.txt")
        if token_file.exists():
            token = token_file.read_text().strip()
            print()
            print(Colors.green("✅ User token obtained successfully"))
            return token
        else:
            print()
            print(Colors.red("❌ Token file not found after authentication"))
            return None

    except Exception as e:
        print(Colors.red(f"❌ Error running get-user-token.py: {e}"))
        return None


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
                "audience": audience,
                "scope": "openid mcp:read mcp:write"
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


def discover_plugins(plugins_dir: Path) -> List:
    """Discover all test plugins in the plugins directory."""
    plugins = []

    if not plugins_dir.exists():
        return plugins

    # Import plugins package
    sys.path.insert(0, str(plugins_dir.parent))

    for plugin_file in plugins_dir.glob("test_*.py"):
        try:
            # Import the module
            module_name = f"plugins.{plugin_file.stem}"
            module = importlib.import_module(module_name)

            # Find TestPlugin subclasses
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # Check if it's a TestPlugin subclass (but not TestPlugin itself)
                if (hasattr(obj, 'test') and
                    callable(obj.test) and
                    obj.__module__ == module_name):
                    plugins.append(obj())

        except Exception as e:
            print(Colors.yellow(f"⚠️  Failed to load plugin {plugin_file.name}: {e}"))

    return plugins


async def run_automated_tests(transport: str, url: str = None, token: str = None,
                              token_file: str = None, auth0_config_path: str = "auth0-config.json",
                              output_file: str = None, output_format: str = "json") -> int:
    """
    Run automated tests using plugin system.

    Args:
        transport: 'stdio' or 'http'
        url: HTTP URL if transport is 'http'
        token: JWT bearer token for HTTP authentication
        token_file: Path to file containing JWT token
        auth0_config_path: Path to auth0-config.json for automatic token retrieval
        output_file: Path to save test results (optional)
        output_format: Format for saved results ('json' or 'junit')

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    print("=" * 70)
    print(Colors.blue("CloudNativePG MCP Server - Automated Test Suite"))
    print("=" * 70)
    print()

    # Discover plugins
    plugins_dir = Path(__file__).parent / "plugins"
    plugins = discover_plugins(plugins_dir)

    if not plugins:
        print(Colors.yellow("⚠️  No test plugins found"))
        print(f"   Expected plugins in: {plugins_dir}")
        print()
        print("To create a test plugin, add a file like test/plugins/test_my_tool.py:")
        print("  from plugins import TestPlugin, TestResult")
        print("  class MyToolTest(TestPlugin):")
        print("      tool_name = 'my_tool'")
        print("      async def test(self, session): ...")
        return 1

    print(f"📋 Discovered {len(plugins)} test plugin(s)")
    for plugin in plugins:
        print(f"   • {plugin.tool_name}: {plugin.description}")
    print()

    # Setup MCP client based on transport
    if transport == 'stdio':
        print(Colors.blue("Transport: stdio"))
        print(f"Command: python src/cnpg_mcp_server.py")
        print()

        try:
            from mcp.client.stdio import stdio_client, StdioServerParameters
            from mcp.client.session import ClientSession

            server_params = StdioServerParameters(
                command="python",
                args=["src/cnpg_mcp_server.py"],
            )

            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    # Initialize
                    init_result = await session.initialize()
                    print(Colors.green(f"✅ Connected to server"))
                    print(f"   Name: {init_result.serverInfo.name}")
                    print(f"   Version: {init_result.serverInfo.version}")
                    print()

                    # Run all plugins
                    exit_code, results = await run_plugin_tests(session, plugins)

                    # Save results if requested
                    if output_file:
                        save_test_results(results, output_file, output_format, transport, url)

                    return exit_code

        except ImportError as e:
            print(Colors.red(f"❌ Failed to import MCP client library: {e}"))
            print()
            print("Install with: pip install mcp")
            return 1
        except Exception as e:
            print(Colors.red(f"❌ Failed to start server: {e}"))
            return 1

    else:  # HTTP transport
        print(Colors.blue("Transport: HTTP"))
        print(f"URL: {url}")
        print()

        # Get authentication token with priority:
        # 1. Manual token via --token
        # 2. Token file via --token-file
        # 3. Auto-obtain from auth0-config.json
        auth_token = None
        token_source = None

        if token:
            auth_token = token.strip()
            token_source = "command line argument"
        elif token_file:
            token_path = Path(token_file)
            if not token_path.exists():
                print(Colors.red(f"❌ Token file not found: {token_file}"))
                return 1
            auth_token = token_path.read_text().strip()
            if not auth_token:
                print(Colors.red(f"❌ Token file is empty: {token_file}"))
                return 1
            token_source = f"file: {token_file}"
        else:
            # Try auto-obtain from auth0-config.json
            auth0_config = load_auth0_config(auth0_config_path)

            if auth0_config:
                print(Colors.green(f"✅ Found {auth0_config_path}"))
                print()
                auth_token = get_token_from_auth0(auth0_config)

                if auth_token:
                    token_source = f"auto-obtained from {auth0_config_path}"
                else:
                    # Try user authentication as fallback
                    print(Colors.yellow("⚠️  Client credentials failed, trying user authentication..."))
                    print()
                    auth_token = get_user_token_interactive()

                    if auth_token:
                        token_source = "user authentication (Authorization Code Flow)"
                    else:
                        print()
                        print(Colors.red("❌ Failed to obtain authentication token"))
                        return 1
            else:
                print(Colors.yellow(f"⚠️  No {auth0_config_path} found"))
                print("   Attempting connection without authentication...")
                print()

        if auth_token:
            print(Colors.green(f"✅ Using token from: {token_source}"))
            print()

        try:
            from mcp.client.streamable_http import streamablehttp_client
            from mcp.client.session import ClientSession

            # Construct MCP endpoint URL
            mcp_url = f"{url}/mcp" if not url.endswith('/mcp') else url

            # Prepare headers
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"

            print(Colors.blue(f"Connecting to: {mcp_url}"))
            print()

            async with streamablehttp_client(mcp_url, headers=headers) as (read, write, get_session_id):
                async with ClientSession(read, write) as session:
                    # Initialize
                    init_result = await session.initialize()
                    print(Colors.green(f"✅ Connected to server"))
                    print(f"   Name: {init_result.serverInfo.name}")
                    print(f"   Version: {init_result.serverInfo.version}")
                    print()

                    # Run all plugins
                    exit_code, results = await run_plugin_tests(session, plugins)

                    # Save results if requested
                    if output_file:
                        save_test_results(results, output_file, output_format, transport, url)

                    return exit_code

        except ImportError as e:
            print(Colors.red(f"❌ Failed to import MCP Streamable HTTP client library: {e}"))
            print()
            print("Install with: pip install mcp")
            return 1
        except Exception as e:
            print(Colors.red(f"❌ Failed to connect to server: {e}"))
            import traceback
            traceback.print_exc()
            return 1


async def run_plugin_tests(session, plugins: List) -> tuple[int, List]:
    """
    Run all plugin tests and report results.

    Returns:
        Tuple of (exit_code, results_list)
    """
    print("=" * 70)
    print("Running Tests")
    print("=" * 70)
    print()

    results = []
    passed = 0
    failed = 0

    for plugin in plugins:
        print(f"▶️  {plugin.get_name()}...", end=" ", flush=True)

        try:
            result = await plugin.test(session)
            results.append(result)

            if result.passed:
                print(Colors.green("✅ PASS"))
                passed += 1
            else:
                print(Colors.red("❌ FAIL"))
                failed += 1

            # Show details
            if result.duration_ms:
                print(f"   Duration: {result.duration_ms:.1f}ms")
            print(f"   {result.message}")
            if result.error:
                print(Colors.red(f"   Error: {result.error}"))
            print()

        except Exception as e:
            print(Colors.red("❌ EXCEPTION"))
            print(Colors.red(f"   Unexpected error: {e}"))
            print()
            failed += 1

            # Create a failed result for the exception
            from plugins import TestResult
            results.append(TestResult(
                plugin_name=plugin.get_name(),
                tool_name=plugin.tool_name,
                passed=False,
                message=f"Unexpected exception during test",
                error=str(e)
            ))

    # Summary
    print("=" * 70)
    print("Test Summary")
    print("=" * 70)
    print()
    print(f"Total:  {passed + failed} tests")
    print(Colors.green(f"Passed: {passed}"))
    print(Colors.red(f"Failed: {failed}"))
    print()

    if failed == 0:
        print(Colors.green("🎉 All tests passed!"))
        exit_code = 0
    else:
        print(Colors.red(f"❌ {failed} test(s) failed"))
        exit_code = 1

    return exit_code, results


def save_test_results(results: List, output_file: str, format: str = "json",
                      transport: str = "stdio", url: str = None):
    """
    Save test results to a file.

    Args:
        results: List of TestResult objects
        output_file: Path to output file
        format: Output format ('json' or 'junit')
        transport: Transport mode used
        url: URL if HTTP transport was used
    """
    from datetime import datetime, timezone

    if format == "json":
        # Create JSON structure
        output = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "transport": transport,
            "url": url if transport == "http" else None,
            "summary": {
                "total": len(results),
                "passed": sum(1 for r in results if r.passed),
                "failed": sum(1 for r in results if not r.passed),
                "duration_ms": sum(r.duration_ms or 0 for r in results)
            },
            "tests": [
                {
                    "plugin_name": r.plugin_name,
                    "tool_name": r.tool_name,
                    "passed": r.passed,
                    "message": r.message,
                    "error": r.error,
                    "duration_ms": r.duration_ms
                }
                for r in results
            ]
        }

        with open(output_file, 'w') as f:
            json.dump(output, f, indent=2)

        print()
        print(Colors.green(f"✅ Test results saved to: {output_file}"))
        print(f"   Format: JSON")

    elif format == "junit":
        # Create JUnit XML structure
        import xml.etree.ElementTree as ET

        total = len(results)
        failures = sum(1 for r in results if not r.passed)
        duration_s = sum(r.duration_ms or 0 for r in results) / 1000.0

        testsuite = ET.Element("testsuite", {
            "name": "MCP Automated Tests",
            "tests": str(total),
            "failures": str(failures),
            "errors": "0",
            "time": f"{duration_s:.3f}",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        })

        # Add properties
        properties = ET.SubElement(testsuite, "properties")
        ET.SubElement(properties, "property", {"name": "transport", "value": transport})
        if url:
            ET.SubElement(properties, "property", {"name": "url", "value": url})

        # Add test cases
        for r in results:
            testcase = ET.SubElement(testsuite, "testcase", {
                "name": r.plugin_name,
                "classname": f"mcp.tools.{r.tool_name}",
                "time": f"{(r.duration_ms or 0) / 1000:.3f}"
            })

            if not r.passed:
                failure = ET.SubElement(testcase, "failure", {
                    "message": r.message
                })
                if r.error:
                    failure.text = r.error

        # Write XML
        tree = ET.ElementTree(testsuite)
        ET.indent(tree, space="  ")
        tree.write(output_file, encoding="utf-8", xml_declaration=True)

        print()
        print(Colors.green(f"✅ Test results saved to: {output_file}"))
        print(f"   Format: JUnit XML")


def main():
    parser = argparse.ArgumentParser(
        description="CloudNativePG MCP Server Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run automated tests (default mode with stdio)
  ./test-mcp.py

  # Run automated tests with HTTP transport
  ./test-mcp.py --transport http --url https://cnpg-mcp.wat.im

  # Save test results to JSON file
  ./test-mcp.py --output results.json

  # Save test results to JUnit XML (for CI/CD)
  ./test-mcp.py --output results.xml --format junit

  # Launch Inspector UI for manual testing
  ./test-mcp.py --use-inspector

  # Inspector with HTTP and auth proxy (easiest for manual testing)
  ./test-mcp.py --use-inspector --transport http --url https://cnpg-mcp.wat.im --use-proxy

  # Inspector with kubectl port-forward
  ./test-mcp.py --use-inspector --transport http --port-forward --namespace claude

Testing Modes:
  Default         - Automated tests via plugin system (no Inspector)
  --use-inspector - Launch Inspector UI for manual testing

Transports:
  stdio (default) - Local server as subprocess
  http            - Connect to remote HTTP server

Inspector Options (only with --use-inspector):
  --use-proxy     - Auto-start auth proxy (eliminates manual header setup)
  --port-forward  - Use kubectl to access in-cluster service

Environment Variables:
  MCP_HTTP_URL    Default HTTP URL (default: http://localhost:4204)

Notes:
  - Default mode runs automated tests (fast, CI-friendly)
  - Use --use-inspector for interactive testing/debugging
  - Automated tests use plugin system (test/plugins/test_*.py)
  - Automatically obtains user token when needed
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
        '--use-inspector',
        action='store_true',
        help='Launch Inspector UI for manual testing (default: run automated tests)'
    )
    parser.add_argument(
        '--use-proxy',
        action='store_true',
        help='[Inspector only] Start local auth proxy automatically'
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
    parser.add_argument(
        '-o', '--output',
        dest='output_file',
        help='Save test results to file (automated tests only)'
    )
    parser.add_argument(
        '-f', '--format',
        dest='output_format',
        choices=['json', 'junit'],
        default='json',
        help='Output format for test results (default: json)'
    )

    args = parser.parse_args()

    # Route to automated tests or Inspector based on flag
    if not args.use_inspector:
        # Default: Run automated tests
        exit_code = asyncio.run(run_automated_tests(
            transport=args.transport,
            url=args.url,
            token=args.token,
            token_file=args.token_file,
            auth0_config_path=args.auth0_config,
            output_file=args.output_file,
            output_format=args.output_format
        ))
        sys.exit(exit_code)

    # Inspector mode below - check if npx is available
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

    # Priority 3: Auto-obtain from auth0-config.json (only for HTTP Inspector mode)
    elif args.transport == 'http':
        # Try client credentials, fall back to user auth if needed
        auth0_config = load_auth0_config(args.auth0_config)

        if auth0_config:
            print(Colors.green(f"✅ Found {args.auth0_config}"))
            print()
            token = get_token_from_auth0(auth0_config)
            if token:
                token_source = f"auto-obtained from {args.auth0_config} (client credentials)"
            else:
                # If using proxy (which requires token), try user authentication
                if args.use_proxy:
                    print(Colors.yellow("⚠️  Client credentials failed (likely missing 'openid' scope)"))
                    print()
                    print("Attempting user authentication instead...")
                    token = get_user_token_interactive()
                    if token:
                        token_source = "user authentication (Authorization Code Flow)"
                    else:
                        print()
                        print(Colors.red("❌ Failed to obtain token via user authentication"))
                        sys.exit(1)
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

                # Write token to file for proxy
                token_file = Path("/tmp/mcp-user-token.txt")
                token_file.write_text(token)
                print(f"  Token written to {token_file}")

                # Start auth proxy
                print(Colors.green("Starting auth proxy..."))
                proxy_cmd = [
                    sys.executable,  # Use same Python interpreter
                    './test/mcp-auth-proxy.py',
                    '--backend', args.url,
                    '--port', str(args.proxy_port),
                    '--token-file', str(token_file)
                ]
                print(f"  Command: {' '.join(proxy_cmd)}")

                proxy_proc = subprocess.Popen(
                    proxy_cmd,
                    # Let proxy output show directly
                )
                background_processes.append(('auth proxy', proxy_proc))
                print(f"  PID: {proxy_proc.pid}")

                # Wait a moment for proxy to start
                time.sleep(2)

                # Check if proxy is still running
                if proxy_proc.poll() is not None:
                    print(Colors.red(f"✗ Proxy exited with code {proxy_proc.returncode}"))
                    sys.exit(1)

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

            # Inspector UI mode
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
                        print(f"   ./test-mcp.py --use-inspector --transport http --url {args.url} --use-proxy")
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
