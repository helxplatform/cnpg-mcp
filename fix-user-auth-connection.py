#!/usr/bin/env python3
"""
Debug and fix user auth client connection issues.

This script checks and fixes the "User not allowed for this application" error.
"""

import json
import sys
from pathlib import Path

import requests


def load_auth0_config():
    """Load Auth0 configuration."""
    config_file = Path("auth0-config.json")
    if not config_file.exists():
        print("❌ auth0-config.json not found")
        sys.exit(1)

    with open(config_file) as f:
        return json.load(f)


def main():
    print("=" * 70)
    print("User Auth Connection Fixer")
    print("=" * 70)
    print()

    config = load_auth0_config()

    domain = config.get("domain")
    mgmt_api = config.get("management_api", {})
    mgmt_token = mgmt_api.get("client_secret")  # Will get proper token below
    user_client_id = config.get("user_auth_client", {}).get("client_id")
    connection_id = config.get("connection_id")

    if not all([domain, user_client_id, connection_id]):
        print("❌ Missing required config")
        print(f"   Domain: {domain}")
        print(f"   User Client ID: {user_client_id}")
        print(f"   Connection ID: {connection_id}")
        sys.exit(1)

    print(f"Domain: {domain}")
    print(f"User Auth Client ID: {user_client_id}")
    print(f"Connection ID: {connection_id}")
    print()

    # Get management API token
    print("🔑 Getting management API token...")
    mgmt_client_id = mgmt_api.get("client_id")
    mgmt_client_secret = mgmt_api.get("client_secret")

    token_response = requests.post(
        f"https://{domain}/oauth/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": mgmt_client_id,
            "client_secret": mgmt_client_secret,
            "audience": f"https://{domain}/api/v2/"
        }
    )

    if token_response.status_code != 200:
        print(f"❌ Failed to get management token: {token_response.text}")
        sys.exit(1)

    mgmt_token = token_response.json()["access_token"]
    print("✅ Got management API token")
    print()

    # Check connection details
    print("🔍 Checking connection configuration...")
    headers = {
        "Authorization": f"Bearer {mgmt_token}",
        "Content-Type": "application/json"
    }

    conn_response = requests.get(
        f"https://{domain}/api/v2/connections/{connection_id}",
        headers=headers
    )

    if conn_response.status_code != 200:
        print(f"❌ Failed to get connection: {conn_response.text}")
        sys.exit(1)

    connection = conn_response.json()

    print(f"Connection Name: {connection.get('name')}")
    print(f"Strategy: {connection.get('strategy')}")
    print(f"Tenant-level: {connection.get('is_domain_connection', False)}")
    print()

    if connection.get("is_domain_connection", False):
        print("✅ Connection is tenant-level (should work for all clients)")
        print()

        # Check what connections are enabled for the user auth client
        print("🔍 Checking which connections are enabled for user auth client...")
        client_response = requests.get(
            f"https://{domain}/api/v2/clients/{user_client_id}",
            headers=headers
        )

        if client_response.status_code == 200:
            client = client_response.json()

            # Get all connections
            all_connections_response = requests.get(
                f"https://{domain}/api/v2/connections",
                headers=headers
            )

            if all_connections_response.status_code == 200:
                all_connections = all_connections_response.json()

                print()
                print("Connections available to user auth client:")
                print()

                for conn in all_connections:
                    conn_id = conn.get("id")
                    conn_name = conn.get("name")
                    strategy = conn.get("strategy")
                    is_domain = conn.get("is_domain_connection", False)
                    enabled_clients = conn.get("enabled_clients", [])

                    # Check if this connection is available to the user auth client
                    if is_domain or user_client_id in enabled_clients:
                        marker = "✅" if conn_id == connection_id else "  "
                        print(f"{marker} {conn_name} ({strategy})")
                        if conn_id == connection_id:
                            print(f"     ← This is the connection setup-auth0.py configured")

                print()
                print("The issue: Your existing user is likely in a DIFFERENT connection")
                print("          than 'Username-Password-Authentication'")
                print()
                print("Solutions:")
                print("  1. Create a new user in 'Username-Password-Authentication' connection")
                print("     (Auth0 Dashboard → User Management → Users → Create User)")
                print()
                print("  2. OR check which connection your existing user is in and enable it")
                print("     for the MCP user auth client")
                print()
        else:
            print(f"⚠️  Could not fetch client details: {client_response.text}")
            print()
            print("This means the issue might be something else:")
            print("  - Check if you have a user created in 'Username-Password-Authentication'")
            print("  - Check if the user's email is verified")
            print()
    else:
        print("⚠️  Connection is app-level (requires explicit client enablement)")
        enabled_clients = connection.get("enabled_clients", [])
        print(f"Currently enabled for {len(enabled_clients)} clients:")
        for cid in enabled_clients:
            print(f"  - {cid}")
        print()

        if user_client_id in enabled_clients:
            print(f"✅ User auth client is already enabled")
            print()
            print("Since the client is enabled but you're still getting the error,")
            print("try promoting the connection to tenant-level:")
            print()
            print("PATCH https://{domain}/api/v2/connections/{connection_id}")
            print('{"is_domain_connection": true}')
            print()

            fix = input("Do you want me to promote it now? (y/N): ")
            if fix.lower() == 'y':
                print()
                print("🚀 Promoting connection to tenant-level...")
                patch_response = requests.patch(
                    f"https://{domain}/api/v2/connections/{connection_id}",
                    headers=headers,
                    json={"is_domain_connection": True}
                )

                if patch_response.status_code == 200:
                    print("✅ Connection promoted to tenant-level!")
                    print("   Try get-user-token.py again")
                else:
                    print(f"❌ Failed to promote: {patch_response.text}")
        else:
            print(f"❌ User auth client is NOT enabled for this connection")
            print()
            print("Fixing this by adding the client to enabled_clients...")
            print()

            enabled_clients.append(user_client_id)

            patch_response = requests.patch(
                f"https://{domain}/api/v2/connections/{connection_id}",
                headers=headers,
                json={"enabled_clients": enabled_clients}
            )

            if patch_response.status_code == 200:
                print("✅ Enabled connection for user auth client!")
                print()
                print("Try get-user-token.py again")
            else:
                print(f"❌ Failed to enable: {patch_response.text}")


if __name__ == "__main__":
    main()
