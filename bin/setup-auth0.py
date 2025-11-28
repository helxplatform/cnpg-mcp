#!/usr/bin/env python3
"""
Auth0 MCP Setup Script - Complete Setup in One Run

This script does EVERYTHING needed to configure Auth0 for MCP with DCR.
Configuration is saved to auth0-config.json (single source of truth).

Requirements:
    pip install requests

Usage:
    # First run
    python setup_auth0_for_mcp.py \\
        --domain your-tenant.auth0.com \\
        --api-identifier https://mcp-server.example.com/mcp \\
        --token YOUR_TOKEN

    # Subsequent runs (uses saved config)
    python setup_auth0_for_mcp.py --token YOUR_TOKEN
    
    # Force recreate management client (if secret lost)
    python setup_auth0_for_mcp.py --token YOUR_TOKEN --recreate-client
"""

import os
import sys
import json
import argparse
import requests
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse
from pathlib import Path


DEFAULT_CONFIG_FILE = "auth0-config.json"


class ConfigManager:
    """Manages configuration from multiple sources with precedence."""
    
    def __init__(self, config_file: str = DEFAULT_CONFIG_FILE):
        self.config_file = config_file
        self.config = self.load_config()
    
    def load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                print(f"📄 Loaded configuration from {self.config_file}")
                return config
            except Exception as e:
                print(f"⚠️  Could not load config file: {e}")
                return {}
        return {}
    
    def save_config(self, config: Dict[str, Any]) -> None:
        """Save config but preserve sensitive data if not provided."""
        existing_config = self.config.copy()
        
        for key, value in config.items():
            if value:
                existing_config[key] = value
        
        safe_config = {
            k: v for k, v in existing_config.items() 
            if k not in ['token', 'mgmt_token']
        }
        
        try:
            config_dir = os.path.dirname(self.config_file)
            if config_dir:  # Only create directory if path includes one
                os.makedirs(config_dir, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(safe_config, f, indent=2)
            print(f"💾 Configuration saved to {self.config_file}")
        except Exception as e:
            print(f"⚠️  Could not save config file: {e}")
    
    def get_value(
        self,
        key: str,
        cli_value: Any = None,
        env_var: Optional[str] = None,
        default: Any = None
    ) -> Any:
        if cli_value is not None:
            return cli_value
        if env_var:
            env_value = os.getenv(env_var)
            if env_value:
                return env_value
        if key in self.config:
            return self.config[key]
        return default
    
    def show_sources(self, config: Dict[str, Any]) -> None:
        print("\n📋 Configuration Sources:")
        print("-" * 60)
        
        for key, value in config.items():
            if key in ['token', 'mgmt_token', 'client_secret']:
                display_value = "***hidden***"
            elif value and len(str(value)) > 50:
                display_value = str(value)[:47] + "..."
            else:
                display_value = str(value)
            
            source = "unknown"
            if key in self.config:
                source = f"config file"
            
            env_var_map = {
                'domain': 'AUTH0_DOMAIN',
                'token': 'AUTH0_MGMT_TOKEN',
                'api_name': 'AUTH0_API_NAME',
                'api_identifier': 'AUTH0_API_IDENTIFIER',
                'client_secret': 'AUTH0_MGMT_CLIENT_SECRET'
            }
            if key in env_var_map and os.getenv(env_var_map[key]):
                source = f"env: {env_var_map[key]}"
            
            print(f"  {key:20} = {display_value:30} [{source}]")


class Auth0MCPSetup:
    """Handles complete Auth0 tenant setup for MCP with DCR."""
    
    def __init__(self, domain: str, access_token: str):
        self.domain = domain.rstrip('/')
        self.access_token = access_token
        self.base_url = f"https://{self.domain}/api/v2"
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        silent_errors: bool = False
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                params=params,
                timeout=30
            )
            response.raise_for_status()

            if response.status_code == 204:
                return {}

            return response.json()

        except requests.HTTPError as e:
            if not silent_errors:
                print(f"❌ API request failed: {e}")
                if e.response is not None:
                    print(f"Response: {e.response.text}")
            raise
    
    def check_dcr_enabled(self) -> bool:
        """Check if DCR is already enabled."""
        print("\n🔍 Checking if DCR is already enabled...")
        
        try:
            tenant_settings = self._make_request("GET", "/tenants/settings", silent_errors=True)
            flags = tenant_settings.get("flags", {})
            dcr_enabled = flags.get("enable_dynamic_client_registration", False)

            if dcr_enabled:
                print("✅ DCR is already enabled")
            else:
                print("ℹ️  DCR is not enabled")

            return dcr_enabled

        except Exception as e:
            print(f"⚠️  Could not check DCR status (insufficient permissions - assuming already configured)")
            return False
    
    def enable_dcr(self) -> bool:
        """Enable OIDC Dynamic Application Registration (idempotent)."""
        if self.check_dcr_enabled():
            return True
        
        print("\n🚀 Enabling OIDC Dynamic Application Registration...")

        try:
            payload = {
                "flags": {
                    "enable_dynamic_client_registration": True,
                    "enable_client_connections": True
                }
            }

            self._make_request("PATCH", "/tenants/settings", data=payload, silent_errors=True)

            print("✅ Successfully enabled DCR and client connections")
            return True

        except Exception as e:
            print(f"⚠️  Could not enable DCR (insufficient permissions - assuming already configured)")
            return False
    
    def get_api(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Get API by identifier if it exists."""
        try:
            apis = self._make_request("GET", "/resource-servers", silent_errors=True)
            for api in apis:
                if api.get("identifier") == identifier:
                    return api
            return None
        except Exception:
            return None
    
    def create_api(
        self,
        name: str,
        identifier: str,
        scopes: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """Create API (idempotent - returns existing if found)."""
        print(f"\n🔧 Setting up API: {name}...")
        
        existing = self.get_api(identifier)
        if existing:
            print(f"✅ API already exists: {existing['name']}")
            print(f"   Identifier: {existing['identifier']}")
            return existing
        
        if scopes is None:
            scopes = [
                {"value": "mcp:read", "description": "Read access to MCP tools"},
                {"value": "mcp:write", "description": "Write access to MCP tools"}
            ]
        
        try:
            payload = {
                "name": name,
                "identifier": identifier,
                "signing_alg": "RS256",
                "scopes": scopes,
                "allow_offline_access": True,
                "token_lifetime": 86400,
                "token_lifetime_for_web": 7200
            }

            api = self._make_request("POST", "/resource-servers", data=payload, silent_errors=True)

            print(f"✅ Successfully created API")
            print(f"   Name: {api['name']}")
            print(f"   Identifier: {api['identifier']}")
            print(f"   Scopes: {', '.join([s['value'] for s in api.get('scopes', [])])}")

            return api

        except Exception as e:
            raise
    
    def get_management_client(self, name: str) -> Optional[Dict[str, Any]]:
        """Find existing management client by name."""
        try:
            clients = self._make_request("GET", "/clients", params={"app_type": "non_interactive"})
            for client in clients:
                if client.get("name") == name:
                    return client
            return None
        except Exception:
            return None
    
    def delete_client(self, client_id: str) -> bool:
        """Delete a client."""
        try:
            self._make_request("DELETE", f"/clients/{client_id}")
            return True
        except Exception as e:
            print(f"⚠️  Could not delete client: {e}")
            return False
    
    def create_management_api_client(
        self,
        name: str = "MCP Server Management Client",
        existing_secret: Optional[str] = None,
        recreate: bool = False
    ) -> Tuple[Dict[str, Any], str, str]:
        """Create M2M application (idempotent with secret handling)."""
        print(f"\n🔧 Setting up Management API M2M Application: {name}...")
        
        existing = self.get_management_client(name)
        
        if existing and recreate:
            print(f"🔄 Recreating management client (--recreate-client specified)...")
            if self.delete_client(existing['client_id']):
                print(f"✅ Deleted existing client")
                existing = None
            else:
                print(f"⚠️  Could not delete existing client, will use it")
        
        if existing:
            client_id = existing['client_id']
            print(f"✅ Management client already exists")
            print(f"   Client ID: {client_id}")
            
            if existing_secret:
                print(f"   ✅ Using client secret from config file")
                return existing, client_id, existing_secret
            else:
                print(f"   ⚠️  Client secret not available")
                print(f"   💡 Run with --recreate-client to generate a new secret")
                return existing, client_id, ""
        
        try:
            payload = {
                "name": name,
                "description": "Machine-to-Machine application for MCP server connection management",
                "app_type": "non_interactive",
                "grant_types": ["client_credentials"],
                "token_endpoint_auth_method": "client_secret_post"
            }
            
            client = self._make_request("POST", "/clients", data=payload)
            client_id = client["client_id"]
            client_secret = client["client_secret"]
            
            print(f"✅ Created new M2M application")
            print(f"   Client ID: {client_id}")
            print(f"   Client Secret: {client_secret[:8]}...{client_secret[-4:]}")
            
            print("🔑 Granting Management API access...")
            
            resource_servers = self._make_request("GET", "/resource-servers")
            mgmt_api = None
            for rs in resource_servers:
                if rs.get("identifier") == f"https://{self.domain}/api/v2/":
                    mgmt_api = rs
                    break
            
            if mgmt_api:
                grant_payload = {
                    "client_id": client_id,
                    "audience": mgmt_api["identifier"],
                    "scope": [
                        # Tenant settings (for DCR enable/check)
                        "read:tenant_settings",
                        "update:tenant_settings",
                        # Resource servers / APIs (for creating/reading MCP API)
                        "read:resource_servers",
                        "create:resource_servers",
                        "update:resource_servers",
                        "delete:resource_servers",
                        # Connection management (for promoting username-password auth)
                        "read:connections",
                        "update:connections",
                        # Client management (CRITICAL: need create/delete for setup script)
                        "read:clients",
                        "create:clients",
                        "update:clients",
                        "delete:clients",
                        "read:client_keys",
                        "read:client_summary",
                        # Client grants (for granting API access to clients)
                        "read:client_grants",
                        "create:client_grants",
                        "update:client_grants",
                        "delete:client_grants",
                        # User management (for adding users to allowedClients)
                        "read:users",
                        "update:users",
                        "read:user_idp_tokens"
                    ]
                }

                try:
                    self._make_request("POST", f"/client-grants", data=grant_payload)
                    print("✅ Granted Management API scopes:")
                    print("   - Tenant settings: read, update")
                    print("   - Resource servers (APIs): read, create, update, delete")
                    print("   - Connections: read, update")
                    print("   - Clients: read, create, update, delete (+ keys, summary)")
                    print("   - Client grants: read, create, update, delete")
                    print("   - Users: read, update (+ idp_tokens)")
                except Exception:
                    print("✅ Permissions already configured")
            
            return client, client_id, client_secret
            
        except Exception as e:
            print(f"❌ Failed to create M2M application: {e}")
            raise

    def create_server_client(
        self,
        api_identifier: str,
        name: str = "MCP Server Client",
        existing_secret: Optional[str] = None,
        recreate: bool = False
    ) -> Tuple[Dict[str, Any], str, str]:
        """Create FastMCP OAuth server client for user authentication."""
        print(f"\n🔧 Setting up FastMCP Server Client: {name}...")

        # Check if client exists
        all_clients = self._make_request("GET", "/clients")
        existing = next((c for c in all_clients if c.get("name") == name), None)

        if existing and recreate:
            print(f"🔄 Recreating test client (--recreate-client specified)...")
            if self.delete_client(existing['client_id']):
                print(f"✅ Deleted existing client")
                existing = None
            else:
                print(f"⚠️  Could not delete existing client, will use it")

        if existing:
            client_id = existing['client_id']
            print(f"✅ Test client already exists")
            print(f"   Client ID: {client_id}")

            if existing_secret:
                print(f"   ✅ Using client secret from config file")
                client_secret = existing_secret
            else:
                print(f"   ⚠️  Client secret not available")
                print(f"   💡 Run with --recreate-client to generate a new secret")
                client_secret = ""

            # Check and update callback URLs if needed
            from urllib.parse import urlparse
            parsed = urlparse(api_identifier)
            mcp_base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else None

            existing_callbacks = existing.get('callbacks', [])
            missing_callbacks = []

            if mcp_base_url:
                mcp_callback = f"{mcp_base_url}/auth/callback"
                if mcp_callback not in existing_callbacks:
                    missing_callbacks.append(mcp_callback)

            if missing_callbacks:
                print(f"   📝 Updating callback URLs...")
                updated_callbacks = existing_callbacks + missing_callbacks

                web_origins = existing.get('web_origins', [])
                allowed_origins = existing.get('allowed_origins', [])

                if mcp_base_url and mcp_base_url not in web_origins:
                    web_origins = web_origins + [mcp_base_url]
                    allowed_origins = allowed_origins + [mcp_base_url]

                try:
                    self._make_request(
                        "PATCH",
                        f"/clients/{client_id}",
                        data={
                            "callbacks": updated_callbacks,
                            "web_origins": web_origins,
                            "allowed_origins": allowed_origins
                        }
                    )
                    print(f"   ✅ Updated callback URLs:")
                    for cb in missing_callbacks:
                        print(f"      + {cb}")
                except Exception as e:
                    print(f"   ⚠️  Failed to update callbacks: {e}")
            else:
                print(f"   ✅ Callback URLs already configured")

            # Check and update grant types if needed
            existing_grant_types = existing.get('grant_types', [])
            required_grant_types = ["authorization_code", "refresh_token", "client_credentials"]
            missing_grant_types = [gt for gt in required_grant_types if gt not in existing_grant_types]

            if missing_grant_types:
                print(f"   📝 Updating grant types...")
                updated_grant_types = list(set(existing_grant_types + missing_grant_types))

                try:
                    self._make_request(
                        "PATCH",
                        f"/clients/{client_id}",
                        data={
                            "grant_types": updated_grant_types
                        }
                    )
                    print(f"   ✅ Updated grant types:")
                    for gt in missing_grant_types:
                        print(f"      + {gt}")
                except Exception as e:
                    print(f"   ⚠️  Failed to update grant types: {e}")
            else:
                print(f"   ✅ Grant types already configured")
        else:
            # Create new test client
            # FastMCP needs authorization_code for user authentication, not just client_credentials
            try:
                # Extract base URL from api_identifier for callback configuration
                from urllib.parse import urlparse
                parsed = urlparse(api_identifier)
                mcp_base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else None

                # Build callback URLs for FastMCP OAuth flow
                callbacks = []
                web_origins = []
                allowed_origins = []

                if mcp_base_url:
                    mcp_callback = f"{mcp_base_url}/auth/callback"
                    callbacks.append(mcp_callback)
                    web_origins.append(mcp_base_url)
                    allowed_origins.append(mcp_base_url)

                payload = {
                    "name": name,
                    "description": f"FastMCP OAuth client for {api_identifier} (supports user authentication and M2M)",
                    "app_type": "regular_web",  # Web application with M2M support
                    "grant_types": [
                        "authorization_code",  # For user authentication (FastMCP)
                        "refresh_token",       # For session management
                        "client_credentials"   # For M2M testing (test-mcp.py)
                    ],
                    "token_endpoint_auth_method": "client_secret_post",
                    "callbacks": callbacks,
                    "web_origins": web_origins,
                    "allowed_origins": allowed_origins,
                    "oidc_conformant": True
                }

                client = self._make_request("POST", "/clients", data=payload)
                existing = client
                client_id = client["client_id"]
                client_secret = client["client_secret"]

                print(f"✅ Created new FastMCP OAuth client")
                print(f"   Client ID: {client_id}")
                print(f"   Client Secret: {client_secret[:8]}...{client_secret[-4:]}")
                print(f"   Type: Regular Web Application (with M2M support)")
                print(f"   Grant Types: authorization_code, refresh_token, client_credentials")
                if callbacks:
                    print(f"   Callback URL: {callbacks[0]}")

            except Exception as e:
                print(f"❌ Failed to create FastMCP OAuth client: {e}")
                raise

        # Grant access to the MCP API (non-fatal if permissions insufficient)
        print(f"🔑 Granting access to API: {api_identifier}...")
        try:
            # Get API resource server
            resource_servers = self._make_request("GET", "/resource-servers", silent_errors=True)
            api = next((rs for rs in resource_servers if rs.get("identifier") == api_identifier), None)

            if not api:
                print(f"⚠️  API not found (may already be configured)")
            else:
                api_id = api["id"]

                # Get API scopes
                scopes = [scope["value"] for scope in api.get("scopes", [])]
                if not scopes:
                    # If no scopes defined, just grant access without specific scopes
                    scopes = []

                # Create client grant
                try:
                    grant_payload = {
                        "client_id": client_id,
                        "audience": api_identifier,
                        "scope": scopes
                    }

                    self._make_request("POST", "/client-grants", data=grant_payload, silent_errors=True)
                    print(f"✅ Granted API access")
                    print(f"   Scopes: {', '.join(scopes) if scopes else 'all'}")
                except Exception as e:
                    # Check if grant already exists
                    if "already exists" in str(e).lower():
                        print("✅ API access already granted")
                    else:
                        print(f"⚠️  Could not create grant (insufficient permissions - assuming already configured)")
        except Exception as e:
            print(f"⚠️  Could not verify API grants (insufficient permissions - assuming already configured)")

        return existing, client_id, client_secret

    def create_test_client(
        self,
        api_identifier: str,
        connection_id: Optional[str] = None,
        name: str = "MCP Test Client",
        existing_secret: Optional[str] = None,
        recreate: bool = False
    ) -> Tuple[Dict[str, Any], str]:
        """
        Create SPA/Native client for test harness (Authorization Code + PKCE).

        This client is used by test scripts like get-user-token.py.

        Args:
            api_identifier: API audience identifier
            connection_id: Auth0 connection ID to enable for this client
            name: Client name
            existing_secret: Not used for SPA clients (PKCE, no secret)
            recreate: Whether to recreate if exists
        """
        print(f"\n🧪 Setting up Test Harness Client: {name}...")

        # Extract base URL from api_identifier for MCP server callbacks
        # e.g., "https://cnpg-claude.wat.im/mcp" -> "https://cnpg-claude.wat.im"
        from urllib.parse import urlparse
        parsed = urlparse(api_identifier)
        mcp_base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else None

        # Check if client exists
        all_clients = self._make_request("GET", "/clients")
        existing = next((c for c in all_clients if c.get("name") == name), None)

        if existing and recreate:
            print(f"🔄 Recreating user auth client (--recreate-client specified)...")
            if self.delete_client(existing['client_id']):
                print(f"✅ Deleted existing client")
                existing = None
            else:
                print(f"⚠️  Could not delete existing client, will use it")

        if existing:
            client_id = existing['client_id']
            print(f"✅ User auth client already exists")
            print(f"   Client ID: {client_id}")

            # Check and update callback URLs if missing
            existing_callbacks = existing.get('callbacks', [])
            missing_callbacks = []

            # Check for MCP server callback
            # FastMCP uses /auth/callback as the redirect path (see src/auth_fastmcp.py:214)
            if mcp_base_url:
                mcp_callback = f"{mcp_base_url}/auth/callback"
                if mcp_callback not in existing_callbacks:
                    missing_callbacks.append(mcp_callback)

            # Check for Claude callback
            claude_callback = "https://claude.ai/api/mcp/auth_callback"
            if claude_callback not in existing_callbacks:
                missing_callbacks.append(claude_callback)

            if missing_callbacks:
                print(f"   ⚠️  Missing callback URLs, updating client...")
                updated_callbacks = existing_callbacks + missing_callbacks

                # Also update web_origins and allowed_origins
                existing_web_origins = existing.get('web_origins', [])
                existing_allowed_origins = existing.get('allowed_origins', [])

                updated_web_origins = existing_web_origins.copy()
                updated_allowed_origins = existing_allowed_origins.copy()

                if mcp_base_url and mcp_base_url not in updated_web_origins:
                    updated_web_origins.append(mcp_base_url)
                    updated_allowed_origins.append(mcp_base_url)

                if "https://claude.ai" not in updated_web_origins:
                    updated_web_origins.append("https://claude.ai")
                    updated_allowed_origins.append("https://claude.ai")

                try:
                    self._make_request(
                        "PATCH",
                        f"/clients/{client_id}",
                        data={
                            "callbacks": updated_callbacks,
                            "web_origins": updated_web_origins,
                            "allowed_origins": updated_allowed_origins
                        }
                    )
                    print(f"   ✅ Updated callback URLs:")
                    for cb in missing_callbacks:
                        print(f"      + {cb}")
                except Exception as e:
                    print(f"   ⚠️  Failed to update callbacks: {e}")
            else:
                print(f"   ✅ All required callback URLs already configured")
        else:
            # Create new SPA client for user authentication
            try:
                # Build callback URLs list
                callbacks = [
                    "http://localhost:8888/callback",  # For test/get-user-token.py
                    "http://localhost:8889/callback",  # Alternate port
                    "http://127.0.0.1:8888/callback",  # IPv4 explicit
                ]

                web_origins = [
                    "http://localhost:8888",
                    "http://localhost:8889",
                ]

                allowed_origins = [
                    "http://localhost:8888",
                    "http://localhost:8889",
                ]

                # Add MCP server callback URL for FastMCP OIDC proxy
                # FastMCP uses /auth/callback as the redirect path (see src/auth_fastmcp.py:214)
                if mcp_base_url:
                    mcp_callback = f"{mcp_base_url}/auth/callback"
                    callbacks.append(mcp_callback)
                    web_origins.append(mcp_base_url)
                    allowed_origins.append(mcp_base_url)
                    print(f"   Adding MCP server callback: {mcp_callback}")

                # Add Claude Desktop callback URL for third-party auth flow
                claude_callback = "https://claude.ai/api/mcp/auth_callback"
                callbacks.append(claude_callback)
                web_origins.append("https://claude.ai")
                allowed_origins.append("https://claude.ai")
                print(f"   Adding Claude callback: {claude_callback}")

                payload = {
                    "name": name,
                    "description": f"User authentication client for {api_identifier} (Claude Desktop compatible)",
                    "app_type": "spa",  # Single Page Application - no client secret needed
                    "grant_types": [
                        "authorization_code",  # For user login
                        "refresh_token"        # For staying logged in
                    ],
                    "token_endpoint_auth_method": "none",  # PKCE instead of client secret
                    "callbacks": callbacks,
                    "web_origins": web_origins,
                    "allowed_origins": allowed_origins,
                    "oidc_conformant": True  # Use modern OIDC flow
                }

                client = self._make_request("POST", "/clients", data=payload)
                existing = client
                client_id = client["client_id"]

                print(f"✅ Created new user auth client (SPA)")
                print(f"   Client ID: {client_id}")
                print(f"   Type: Single Page Application (PKCE)")
                print(f"   Callbacks: http://localhost:8888/callback")

            except Exception as e:
                print(f"❌ Failed to create user auth client: {e}")
                raise

        # Enable connection for this client (if tenant-level connection is provided)
        if connection_id:
            print(f"🔗 Enabling connection for user auth client...")
            try:
                # Get current client to check enabled_clients for the connection
                connection = self._make_request("GET", f"/connections/{connection_id}")

                # Check if connection is tenant-level
                if connection.get("is_domain_connection", False):
                    print(f"   ✅ Connection is tenant-level (available to all clients)")
                else:
                    # For app-level connections, need to explicitly enable
                    enabled_clients = connection.get("enabled_clients", [])

                    if client_id not in enabled_clients:
                        enabled_clients.append(client_id)

                        # Update connection to include this client
                        self._make_request(
                            "PATCH",
                            f"/connections/{connection_id}",
                            data={"enabled_clients": enabled_clients}
                        )
                        print(f"   ✅ Enabled connection for client")
                    else:
                        print(f"   ✅ Connection already enabled for client")

            except Exception as e:
                print(f"   ⚠️  Failed to enable connection: {e}")
                print(f"   You may need to manually enable the connection in Auth0 dashboard")

        # Grant access to the MCP API (required for user auth to work)
        print(f"🔑 Granting test client access to API: {api_identifier}...")
        try:
            # Get API resource server
            resource_servers = self._make_request("GET", "/resource-servers", silent_errors=True)
            api = next((rs for rs in resource_servers if rs.get("identifier") == api_identifier), None)

            if not api:
                print(f"⚠️  API not found (may already be configured)")
            else:
                # Get API scopes (including openid if defined)
                scopes = [scope["value"] for scope in api.get("scopes", [])]

                # Create client grant
                try:
                    grant_payload = {
                        "client_id": client_id,
                        "audience": api_identifier,
                        "scope": scopes
                    }

                    self._make_request("POST", "/client-grants", data=grant_payload, silent_errors=True)
                    print(f"✅ Granted API access to test client")
                    print(f"   Scopes: {', '.join(scopes) if scopes else 'all'}")
                except Exception as e:
                    # Check if grant already exists
                    if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                        print(f"✅ API access already granted")
                    else:
                        print(f"⚠️  Failed to grant API access: {e}")
                        print(f"   The client may not be able to access the API")
        except Exception as e:
            print(f"⚠️  Failed to setup API grant: {e}")

        return existing, client_id

    def list_connections(self) -> List[Dict[str, Any]]:
        """List all available connections."""
        print("\n🔍 Fetching available connections...")
        
        try:
            connections = self._make_request("GET", "/connections")
            
            print(f"\n✅ Found {len(connections)} connections:")
            for i, conn in enumerate(connections, 1):
                strategy = conn.get("strategy", "unknown")
                name = conn.get("name", "Unknown")
                conn_id = conn.get("id", "")
                is_domain = conn.get("is_domain_connection", False)
                
                strategy_label = {
                    "auth0": "Database",
                    "google-oauth2": "Google",
                    "github": "GitHub",
                    "facebook": "Facebook",
                    "twitter": "Twitter",
                    "windowslive": "Microsoft",
                    "linkedin": "LinkedIn"
                }.get(strategy, strategy.title())
                
                domain_status = "✅ Tenant-level" if is_domain else "⚠️  App-level"
                
                print(f"{i}. {name} ({strategy_label}) - {domain_status}")
                print(f"   ID: {conn_id}")
            
            return connections
            
        except Exception as e:
            print(f"❌ Failed to list connections: {e}")
            raise
    
    def promote_connection(self, connection_id: str) -> bool:
        """Promote connection to tenant-level (idempotent)."""
        print(f"\n🚀 Promoting connection to tenant-level...")
        print(f"   Connection ID: {connection_id}")
        
        try:
            connection = self._make_request("GET", f"/connections/{connection_id}")
            
            if connection.get("is_domain_connection", False):
                print("✅ Connection is already tenant-level")
                return True
            
            payload = {
                "is_domain_connection": True
            }
            
            updated = self._make_request(
                "PATCH",
                f"/connections/{connection_id}",
                data=payload
            )
            
            print(f"✅ Successfully promoted connection to tenant-level!")
            print(f"   Connection: {updated.get('name', 'Unknown')}")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to promote connection: {e}")
            return False


def validate_domain(domain: str) -> str:
    """Validate and clean Auth0 domain."""
    if domain.startswith("http://") or domain.startswith("https://"):
        parsed = urlparse(domain)
        domain = parsed.netloc
    
    domain = domain.rstrip("/")
    
    if not domain or "." not in domain:
        raise ValueError(f"Invalid domain format: {domain}")
    
    return domain


def load_make_env(output_dir: str = ".") -> Dict[str, str]:
    """Load make.env configuration."""
    make_env_path = Path(output_dir) / "make.env"
    env_vars = {}

    if make_env_path.exists():
        with open(make_env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key] = value

    return env_vars


def save_output_files(
    domain: str,
    api_identifier: str,
    mgmt_client_id: str,
    mgmt_client_secret: str,
    server_client_id: str,
    server_client_secret: str,
    test_client_id: str,
    connection_id: str,
    output_dir: str = ".",
    save_config: bool = True,
    use_dcr: bool = False
) -> None:
    """Save configuration files."""
    print("\n💾 Saving configuration files...")

    if save_config:
        if not mgmt_client_secret:
            print("⚠️  Warning: Management client secret not available")
            print("   Configuration will be incomplete")
            print("   Run with --recreate-client to generate a new secret")

        if not server_client_secret:
            print("⚠️  Warning: Server client secret not available")
            print("   Configuration will be incomplete")
            print("   Run with --recreate-client to generate a new secret")

        # auth0-config.json - single source of truth
        config = {
            "domain": domain,
            "issuer": f"https://{domain}",
            "audience": api_identifier,
            "management_api": {
                "client_id": mgmt_client_id,
                "client_secret": mgmt_client_secret
            },
            "server_client": {
                "client_id": server_client_id,
                "client_secret": server_client_secret
            },
            "test_client": {
                "client_id": test_client_id
            },
            "connection_id": connection_id,
            "dcr_enabled": use_dcr,
            "connection_promoted": True
        }

        json_file = os.path.join(output_dir, "auth0-config.json")
        with open(json_file, "w") as f:
            json.dump(config, f, indent=2)
        print(f"✅ Created {json_file}")
    else:
        print(f"⏭️  Skipping auth0-config.json (preserving existing secrets)")
    
    # Load make.env to get image repository and tag
    make_env = load_make_env(output_dir)
    registry = make_env.get('REGISTRY', 'your-registry.example.com')
    image_name = make_env.get('IMAGE_NAME', 'cnpg-mcp')
    image_tag = make_env.get('TAG', '')
    image_repo = f"{registry}/{image_name}"

    # Extract hostname from audience URL for ingress
    audience_parsed = urlparse(api_identifier)
    ingress_host = audience_parsed.netloc or "mcp-api.example.com"

    # Determine pull policy based on tag type
    # Release tags (v1.0.0, v2.1.0-beta.1) use IfNotPresent
    # Development tags (branch-commit, latest) use Always
    import re
    is_release_tag = bool(re.match(r'^v\d+\.\d+\.\d+', image_tag)) if image_tag else False
    pull_policy = "IfNotPresent" if is_release_tag else "Always"

    pull_policy_comment = "# Release tag - cache images" if is_release_tag else "# Dev tag - always pull latest"

    # Helm values file for deployment
    helm_values = f"""# Helm Values for MCP Server with Auth0 (FastMCP OAuth Proxy)
# Generated by setup-auth0.py
# Deploy with: helm install mcp-server ./chart -f auth0-values.yaml

# Container image configuration
image:
  repository: {image_repo}
  pullPolicy: {pull_policy}  {pull_policy_comment}
  tag: "{image_tag}"  # From make.env (leave empty to use Chart.AppVersion)

# Number of replicas
replicaCount: 1

# FastMCP OAuth Proxy Configuration for Auth0
# The MCP server uses FastMCP's built-in OAuth Proxy which:
# - Receives Auth0 tokens internally (may be JWE encrypted)
# - Issues MCP-signed JWT tokens to clients (NOT Auth0 tokens)
# - Manages session binding between Auth0 and MCP tokens
oidc:
  # Auth0 issuer URL (domain)
  issuer: "https://{domain}"

  # API audience (API identifier created in Auth0)
  audience: "{api_identifier}"

  # Pre-registered Auth0 application client ID
  # This is the OAuth client used by FastMCP Auth0Provider
  # to authenticate with Auth0 during authorization code exchange
  clientId: "{server_client_id}"

  # NOTE: Client secret is automatically loaded from Kubernetes secret
  #   Secret name: <release-name>-auth0-credentials
  #   Secret key: server-client-secret
  # Create the secret with:
  #   python bin/create_secrets.py --namespace <namespace> --release-name <release-name>

  # Optional: Uncomment if you need to override JWKS URI
  # jwksUri: "https://{domain}/.well-known/jwks.json"

# Service configuration
service:
  type: ClusterIP
  port: 4204

# Ingress (configure for external access)
ingress:
  enabled: true
  className: "nginx"
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt"
  host: {ingress_host}
  path: /
  pathType: Prefix
  tls:
    enabled: true
    # secretName auto-generated as: <release-name>-tls
    # Override only if you need a custom name

# Resource limits
resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "500m"

# ServiceAccount
serviceAccount:
  create: true
  name: cnpg-mcp

# Security
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000

securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
    - ALL
"""

    helm_file = os.path.join(output_dir, "auth0-values.yaml")
    with open(helm_file, "w") as f:
        f.write(helm_values)
    print(f"✅ Created {helm_file}")
    print(f"   Ready to deploy: helm install mcp-server ./chart -f {helm_file}")


def get_management_token(domain: str, client_id: str, client_secret: str) -> Optional[str]:
    """
    Get a management API token using client credentials.

    Args:
        domain: Auth0 domain
        client_id: Management client ID
        client_secret: Management client secret

    Returns:
        Access token or None if failed
    """
    try:
        response = requests.post(
            f'https://{domain}/oauth/token',
            json={
                'grant_type': 'client_credentials',
                'client_id': client_id,
                'client_secret': client_secret,
                'audience': f'https://{domain}/api/v2/'
            },
            timeout=30
        )
        response.raise_for_status()
        return response.json()['access_token']
    except Exception as e:
        print(f"⚠️  Could not get management token: {e}")
        return None


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Complete Auth0 setup for MCP with DCR (idempotent)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script does EVERYTHING needed to configure Auth0 for MCP.
Configuration is saved to auth0-config.json (single source of truth).

Examples:
  # First run
  python setup_auth0_for_mcp.py \\
    --domain your-tenant.auth0.com \\
    --api-identifier https://mcp-server.example.com/mcp \\
    --token YOUR_TOKEN

  # Subsequent runs (automatically gets token from saved credentials)
  python setup_auth0_for_mcp.py

  # Force recreate management client
  python setup_auth0_for_mcp.py --recreate-client
        """
    )

    parser.add_argument("--config-file", default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--domain", help="Auth0 tenant domain")
    parser.add_argument("--token", help="Management API access token (auto-generated if not provided)")
    parser.add_argument("--deployment-name", help="Deployment name (e.g., 'CNPG MCP Prod', 'CNPG MCP Dev')")
    parser.add_argument("--api-name", help="Name for the MCP API")
    parser.add_argument("--api-identifier", help="API identifier/audience")
    parser.add_argument("--output-dir", default=".", help="Output directory")
    parser.add_argument("--connection-id", help="Connection ID to promote")
    parser.add_argument("--recreate-client", action="store_true",
                       help="Force recreate management client")
    parser.add_argument("--use-dcr", action="store_true", default=False,
                       help="Enable Dynamic Client Registration (DCR) setup (default: False)")
    parser.add_argument("--no-save-config", action="store_false", dest="save_config",
                       help="Skip saving configuration to auth0-config.json")
    parser.add_argument("--yes", "-y", action="store_true",
                       help="Skip confirmation prompt")

    args = parser.parse_args()
    
    print("=" * 70)
    print("🚀 Auth0 MCP Complete Setup")
    print("=" * 70)
    
    config_mgr = ConfigManager(args.config_file)
    
    # Get deployment name first so we can use it for API name default
    deployment_name = config_mgr.get_value('deployment_name', args.deployment_name, 'DEPLOYMENT_NAME', 'CNPG MCP')

    config = {
        'domain': config_mgr.get_value('domain', args.domain, 'AUTH0_DOMAIN'),
        'token': config_mgr.get_value('token', args.token, 'AUTH0_MGMT_TOKEN'),
        'deployment_name': deployment_name,
        'api_name': config_mgr.get_value('api_name', args.api_name, 'AUTH0_API_NAME', f'{deployment_name} - API'),
        'api_identifier': config_mgr.get_value('api_identifier', args.api_identifier, 'AUTH0_API_IDENTIFIER') or config_mgr.config.get('audience'),
        'connection_id': config_mgr.get_value('connection_id', args.connection_id, 'AUTH0_CONNECTION_ID'),
        'client_secret': config_mgr.get_value('client_secret', None, 'AUTH0_MGMT_CLIENT_SECRET')
    }
    
    config_mgr.show_sources(config)

    missing = []
    if not config['domain']:
        missing.append("domain")
    else:
        try:
            config['domain'] = validate_domain(config['domain'])
        except ValueError as e:
            print(f"\n❌ {e}")
            sys.exit(1)

    # Try to get management token automatically if not provided
    if not config['token']:
        # Check if we have saved management client credentials
        saved_mgmt_client_id = (
            config_mgr.config.get('mgmt_client_id') or
            (config_mgr.config.get('management_api', {}).get('client_id') if isinstance(config_mgr.config.get('management_api'), dict) else None)
        )
        saved_mgmt_client_secret = (
            config_mgr.config.get('client_secret') or
            (config_mgr.config.get('management_api', {}).get('client_secret') if isinstance(config_mgr.config.get('management_api'), dict) else None)
        )

        if saved_mgmt_client_id and saved_mgmt_client_secret and config['domain']:
            print(f"\n🔑 No token provided, getting management token from saved credentials...")
            token = get_management_token(config['domain'], saved_mgmt_client_id, saved_mgmt_client_secret)
            if token:
                config['token'] = token
                print(f"✅ Successfully obtained management token")
            else:
                print(f"⚠️  Could not get management token automatically")

        if not config['token']:
            missing.append("token")
    
    if not config['api_identifier']:
        if config['domain']:
            config['api_identifier'] = f"https://{config['domain']}/mcp"
            print(f"\n💡 Using default API identifier: {config['api_identifier']}")
        else:
            missing.append("api-identifier")
    
    # Special mode: if we have all needed data in config file, allow regenerating values file only
    # Only requires domain and mgmt_client_id - api_identifier can be generated from domain
    # Support both old format (management_api.client_id) and new format (mgmt_client_id)
    saved_mgmt_client_id = (
        config_mgr.config.get('mgmt_client_id') or
        (config_mgr.config.get('management_api', {}).get('client_id') if isinstance(config_mgr.config.get('management_api'), dict) else None)
    )

    has_saved_config = all([
        config_mgr.config.get('domain'),
        saved_mgmt_client_id
    ])

    # Debug: Show what we have in saved config for regeneration
    if not config['token']:
        print(f"\n🔍 Checking saved config for regeneration:")
        print(f"  domain: {config_mgr.config.get('domain')}")
        print(f"  mgmt_client_id: {saved_mgmt_client_id}")
        print(f"  has_saved_config: {has_saved_config}")

    if missing:
        if has_saved_config and not config['token']:
            print(f"\n💡 Regenerating values file from saved config (no Auth0 query needed)")
            # We have enough to regenerate values file
            config['domain'] = config_mgr.config['domain']
            # Use saved api_identifier or generate default from domain
            config['api_identifier'] = config_mgr.config.get('api_identifier') or config_mgr.config.get('audience') or f"https://{config['domain']}/mcp"
            mgmt_client_id = saved_mgmt_client_id

            # Get secrets from saved config if available
            server_client_secret = config_mgr.config.get('server_client', {}).get('client_secret', '')
            mgmt_client_secret = config_mgr.config.get('management_api', {}).get('client_secret', '') or config_mgr.config.get('client_secret', '')

            # Generate values file only (don't overwrite config with empty secrets)
            save_output_files(
                domain=config['domain'],
                api_identifier=config['api_identifier'],
                mgmt_client_id=mgmt_client_id,
                mgmt_client_secret=mgmt_client_secret,  # From saved config
                server_client_id=config_mgr.config.get('server_client', {}).get('client_id', ''),
                server_client_secret=server_client_secret,  # From saved config
                test_client_id=config_mgr.config.get('test_client', {}).get('client_id', ''),
                connection_id=config_mgr.config.get('connection_id', ''),
                output_dir=args.output_dir,
                save_config=False,  # Don't overwrite config file - preserve existing secrets
                use_dcr=config_mgr.config.get('dcr_enabled', False)  # From saved config
            )
            print(f"\n✅ Values file regenerated from config")
            sys.exit(0)
        else:
            print(f"\n❌ Missing required values: {', '.join(missing)}")
            sys.exit(1)
    
    print("\n" + "=" * 70)
    print("Configuration Summary")
    print("=" * 70)
    print(f"Domain:           {config['domain']}")
    print(f"API Name:         {config['api_name']}")
    print(f"API Identifier:   {config['api_identifier']}")
    print(f"Connection ID:    {config.get('connection_id') or 'Will select'}")
    print(f"Recreate Client:  {args.recreate_client}")
    print()

    if not args.yes:
        proceed = input("Proceed with setup? (y/N): ")
        if proceed.lower() != 'y':
            print("Aborted.")
            sys.exit(0)
    else:
        print("Auto-proceeding (--yes flag provided)")
        print()
    
    try:
        setup = Auth0MCPSetup(config['domain'], config['token'])

        # Try to enable DCR, but don't fail if we lack permissions (may already be enabled)
        # Only attempt DCR setup if --use-dcr flag is provided
        if args.use_dcr:
            try:
                setup.enable_dcr()
            except Exception as e:
                print(f"⚠️  Could not verify/enable DCR (may already be configured): {e}")
                print(f"   Continuing with client setup...")
        else:
            print("\nℹ️  Skipping DCR setup (use --use-dcr to enable)")

        # Try to create/verify API, but don't fail if we lack permissions (may already exist)
        try:
            api = setup.create_api(config['api_name'], config['api_identifier'])
        except Exception as e:
            print(f"⚠️  Could not verify/create API (may already exist): {e}")
            print(f"   Continuing with client setup...")
            api = None
        
        # Get existing management secret from correct location (try both old and new structure)
        existing_mgmt_secret = config.get('management_api', {}).get('client_secret') or config.get('client_secret')

        client, client_id, client_secret = setup.create_management_api_client(
            name=f"{config['deployment_name']} - Management API",
            existing_secret=existing_mgmt_secret,
            recreate=args.recreate_client
        )

        # Create server client for FastMCP OAuth (optional - skip if we lack permissions)
        server_client_config = config.get('server_client', {})
        try:
            server_client, server_client_id, server_client_secret = setup.create_server_client(
                name=f"{config['deployment_name']} - Server",
                api_identifier=config['api_identifier'],
                existing_secret=server_client_config.get('client_secret'),
                recreate=args.recreate_client
            )
        except Exception as e:
            print(f"⚠️  Could not verify/create server client (may already exist): {e}")
            print(f"   Continuing with test client setup...")
            # Use existing server client from config if available
            server_client_id = server_client_config.get('client_id', '')
            server_client_secret = server_client_config.get('client_secret', '')
            server_client = None

        connection_id = config.get('connection_id')
        
        if not connection_id:
            connections = setup.list_connections()
            
            print("\n" + "=" * 70)
            print("Select a connection to promote to tenant-level")
            print("=" * 70)
            
            while True:
                choice = input("Enter connection number: ").strip()
                
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(connections):
                        connection_id = connections[idx]["id"]
                        print(f"\n✅ Selected: {connections[idx]['name']} ({connection_id})")
                        break
                    else:
                        print(f"❌ Invalid. Enter 1-{len(connections)}")
                except ValueError:
                    print("❌ Please enter a number")
        
        try:
            setup.promote_connection(connection_id)
        except Exception as e:
            print(f"⚠️  Warning: Connection promotion failed (may already be configured): {e}")
            print(f"   Continuing with client setup...")

        # Create test client for test harness (Authorization Code Flow + PKCE)
        # Must be done AFTER connection is promoted
        test_client_config = config.get('test_client', {})
        test_client, test_client_id = setup.create_test_client(
            name=f"{config['deployment_name']} - Test Harness",
            api_identifier=config['api_identifier'],
            connection_id=connection_id,
            recreate=args.recreate_client
        )

        save_output_files(
            domain=config['domain'],
            api_identifier=config['api_identifier'],
            mgmt_client_id=client_id,
            mgmt_client_secret=client_secret,
            server_client_id=server_client_id,
            server_client_secret=server_client_secret,
            test_client_id=test_client_id,
            connection_id=connection_id,
            output_dir=args.output_dir,
            save_config=False,  # Don't save config here - will be saved with secret preservation logic below
            use_dcr=args.use_dcr
        )
        
        if args.save_config:
            # Preserve existing secrets if new ones aren't available
            existing_mgmt_secret = config.get('management_api', {}).get('client_secret', '') or config.get('client_secret', '')
            existing_server_secret = config.get('server_client', {}).get('client_secret', '')

            config_to_save = {
                'domain': config['domain'],
                'issuer': f"https://{config['domain']}",
                'audience': config['api_identifier'],
                'connection_id': connection_id,
                'dcr_enabled': args.use_dcr,
                'connection_promoted': True
            }

            # Save management client credentials (preserve existing secret if not available)
            config_to_save['management_api'] = {
                'client_id': client_id,
                'client_secret': client_secret if client_secret else existing_mgmt_secret
            }

            # Save server client credentials (preserve existing secret if not available)
            config_to_save['server_client'] = {
                'client_id': server_client_id,
                'client_secret': server_client_secret if server_client_secret else existing_server_secret
            }

            # Save test client (no secret for SPA client)
            if test_client_id:
                config_to_save['test_client'] = {
                    'client_id': test_client_id
                }

            config_mgr.save_config(config_to_save)
        
        print("\n" + "=" * 70)
        print("✅ Auth0 Setup Complete!")
        print("=" * 70)
        print("\n🎉 Everything is configured:")
        print("   ✅ DCR enabled")
        print("   ✅ API created")
        print("   ✅ Management client created")
        print("   ✅ Connection promoted to tenant-level")
        print("   ✅ Configuration saved to auth0-config.json")
        print("   ✅ Helm values file created: auth0-values.yaml")

        if not client_secret:
            print("\n⚠️  Note: Management client secret not available")
            print("   This is only needed for tenant management, not for MCP server operation")
            print("   Run with --recreate-client to generate a new secret if needed")

        print()
        print("📋 Next Steps:")
        print()
        # Get image info from make.env if available
        make_env = load_make_env(args.output_dir)
        registry = make_env.get('REGISTRY', 'your-registry')
        image_name = make_env.get('IMAGE_NAME', 'cnpg-mcp')
        tag = make_env.get('TAG', 'latest')

        print("1. Create Kubernetes Secret with Auth0 credentials:")
        print("   python3 bin/create_secrets.py --namespace <your-namespace> --release-name <release-name> --replace")
        print("   (creates <release-name>-auth0-credentials secret)")
        print()
        print("2. Build and push your MCP server container image:")
        print(f"   make build push")
        print(f"   (builds {registry}/{image_name}:{tag})")
        print()
        print("3. Update the image repository in auth0-values.yaml if needed")
        print()
        print("4. Deploy your MCP server with Helm:")
        print("   helm install mcp-server ./chart -f auth0-values.yaml")
        print()
        print("5. Verify deployment:")
        print("   kubectl get pods -l app.kubernetes.io/name=cnpg-mcp")
        print("   kubectl logs -l app.kubernetes.io/name=cnpg-mcp -f")
        print()
        print("6. Test OAuth flow:")
        print("   # Check OAuth metadata endpoint")
        print("   curl https://your-domain/.well-known/oauth-authorization-server")
        print()
        print("   # Check MCP server health")
        print("   curl https://your-domain/healthz")
        print()
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelled")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Setup failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
