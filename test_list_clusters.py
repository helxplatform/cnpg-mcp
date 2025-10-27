#!/usr/bin/env python3
"""Test the list_clusters tool directly."""

import asyncio
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession


async def test_list_clusters():
    server_params = StdioServerParameters(
        command="python",
        args=["cnpg_mcp_server.py"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("📋 Calling list_postgres_clusters tool...")
            result = await session.call_tool(
                "list_postgres_clusters",
                arguments={}
            )

            print("\n" + "="*60)
            for content in result.content:
                print(content.text)
            print("="*60)


if __name__ == "__main__":
    asyncio.run(test_list_clusters())
