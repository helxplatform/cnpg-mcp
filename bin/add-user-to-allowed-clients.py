#!/usr/bin/env python3
"""
Add MCP clients to user's allowedClients array.

This fixes the "User not allowed for this application" error when
your Auth0 setup uses app_metadata.allowedClients for authorization.

Supports adding users to:
- server: Server client (for Claude Desktop production use)
- test: Test client (for test harness / local testing)
- both: Both clients
"""

import argparse
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


def prompt_client_type():
    """Prompt user to choose which client to add access to."""
    print()
    print("Which client should this user have access to?")
    print()
    print("  1. server  - Server client (for Claude Desktop production)")
    print("  2. test    - Test client (for test harness / local testing)")
    print("  3. both    - Both clients")
    print()

    while True:
        choice = input("Enter choice (1-3): ").strip()
        if choice == "1":
            return "server"
        elif choice == "2":
            return "test"
        elif choice == "3":
            return "both"
        else:
            print("❌ Invalid choice. Please enter 1, 2, or 3.")


def main():
    parser = argparse.ArgumentParser(
        description="Add user to allowed clients for MCP access"
    )
    parser.add_argument(
        "--email",
        help="User email address"
    )
    parser.add_argument(
        "--client-type",
        choices=["server", "test", "both"],
        help="Which client to grant access to (server=production, test=testing, both=both)"
    )

    args = parser.parse_args()

    print("=" * 70)
    print("Add User to Allowed Clients")
    print("=" * 70)
    print()

    config = load_auth0_config()

    domain = config.get("domain")
    mgmt_api = config.get("management_api", {})

    # Get both client IDs
    server_client_id = config.get("server_client", {}).get("client_id")
    test_client_id = config.get("test_client", {}).get("client_id")

    print(f"Domain: {domain}")
    print(f"Server Client ID: {server_client_id}")
    print(f"Test Client ID: {test_client_id}")

    # Determine which client(s) to add
    client_type = args.client_type
    if not client_type:
        client_type = prompt_client_type()

    print()
    print(f"Client Type: {client_type}")
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

    # Get user email
    user_email = args.email
    if not user_email:
        user_email = input("Enter your Auth0 user email: ").strip()

    if not user_email:
        print("❌ Email required")
        sys.exit(1)

    print()
    print(f"🔍 Looking up user: {user_email}")

    headers = {
        "Authorization": f"Bearer {mgmt_token}",
        "Content-Type": "application/json"
    }

    # Search for user by email
    search_response = requests.get(
        f"https://{domain}/api/v2/users",
        headers=headers,
        params={"q": f'email:"{user_email}"'}
    )

    if search_response.status_code != 200:
        print(f"❌ Failed to search users: {search_response.text}")
        sys.exit(1)

    users = search_response.json()

    if not users:
        print(f"❌ User not found: {user_email}")
        sys.exit(1)

    user = users[0]
    user_id = user["user_id"]

    print(f"✅ Found user: {user_id}")
    print()

    # Check current app_metadata
    app_metadata = user.get("app_metadata", {})
    allowed_clients = app_metadata.get("allowedClients", [])

    print(f"Current allowedClients: {allowed_clients}")
    print()

    # Determine which client IDs to add
    clients_to_add = []
    client_names = []

    if client_type in ["server", "both"]:
        if server_client_id and server_client_id not in allowed_clients:
            clients_to_add.append(server_client_id)
            client_names.append("server client")

    if client_type in ["test", "both"]:
        if test_client_id and test_client_id not in allowed_clients:
            clients_to_add.append(test_client_id)
            client_names.append("test client")

    if not clients_to_add:
        print("✅ User already has access to the requested client(s)!")
        print("   No changes needed.")
        sys.exit(0)

    # Add client(s) to allowed clients
    print(f"📝 Adding {', '.join(client_names)} to allowedClients...")
    allowed_clients.extend(clients_to_add)

    patch_response = requests.patch(
        f"https://{domain}/api/v2/users/{user_id}",
        headers=headers,
        json={
            "app_metadata": {
                "allowedClients": allowed_clients
            }
        }
    )

    if patch_response.status_code != 200:
        print(f"❌ Failed to update user: {patch_response.text}")
        sys.exit(1)

    updated_user = patch_response.json()
    updated_allowed = updated_user.get("app_metadata", {}).get("allowedClients", [])

    print("✅ User updated!")
    print()
    print(f"New allowedClients: {updated_allowed}")
    print()
    print("=" * 70)
    print("🎉 Access granted!")
    print("=" * 70)
    print()

    if client_type in ["server", "both"]:
        print("✅ Can now connect via Claude Desktop (server client)")

    if client_type in ["test", "both"]:
        print("✅ Can now run test harness:")
        print("   ./test/get-user-token.py")
        print("   ./test/test-mcp.py --transport http --url https://claude-cnpg.wat.im")

    print()


if __name__ == "__main__":
    main()
