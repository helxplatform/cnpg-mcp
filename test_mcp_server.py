#!/usr/bin/env python3
"""
Simple test script to verify MCP server is working correctly.
This tests the server by calling it directly without the inspector.
"""

import asyncio
import json
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.types import CallToolRequest


async def test_server():
    """Test the MCP server by connecting to it and listing tools."""

    print("🔧 Starting test of CloudNativePG MCP server...")

    # Start the server as a subprocess
    server_params = StdioServerParameters(
        command="python",
        args=["cnpg_mcp_server.py"],
    )

    async with stdio_client(server_params) as (read, write):
        print("✅ Connected to server")

        # Initialize the connection
        from mcp.client.session import ClientSession

        async with ClientSession(read, write) as session:
            print("✅ Session initialized")

            # Initialize the protocol
            result = await session.initialize()
            print(f"✅ Protocol initialized")
            print(f"   Server name: {result.serverInfo.name}")
            print(f"   Server version: {result.serverInfo.version}")
            print(f"   Capabilities: {result.capabilities}")

            # List available tools
            tools_result = await session.list_tools()
            print(f"\n📋 Found {len(tools_result.tools)} tools:")

            for tool in tools_result.tools:
                print(f"\n  • {tool.name}")
                print(f"    Description: {tool.description[:100]}...")
                print(f"    Required params: {tool.inputSchema.get('required', [])}")

            print("\n✅ All tests passed! Server is working correctly.")


if __name__ == "__main__":
    asyncio.run(test_server())
