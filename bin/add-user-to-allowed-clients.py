#!/usr/bin/env python3
"""
Add MCP user auth client to user's allowedClients array.

This fixes the "User not allowed for this application" error when
your Auth0 setup uses app_metadata.allowedClients for authorization.
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
    print("Add User to Allowed Clients")
    print("=" * 70)
    print()

    config = load_auth0_config()

    domain = config.get("domain")
    mgmt_api = config.get("management_api", {})
    # Use server_client (FastMCP OAuth client)
    user_client_id = config.get("server_client", {}).get("client_id")

    print(f"Domain: {domain}")
    print(f"MCP Server Client ID: {user_client_id}")
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

    if user_client_id in allowed_clients:
        print("✅ MCP server client is already in allowedClients!")
        print("   The issue might be something else.")
        sys.exit(0)

    # Add MCP client to allowed clients
    print(f"📝 Adding MCP server client to allowedClients...")
    allowed_clients.append(user_client_id)

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
    print("🎉 You can now authenticate!")
    print("=" * 70)
    print()
    print("Run:")
    print("  ./test/test/get-user-token.py")
    print()


if __name__ == "__main__":
    main()
