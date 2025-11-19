"""Test plugin for server initialization and capabilities."""

import time
from . import TestPlugin, TestResult


class ServerInfoTest(TestPlugin):
    """Test server initialization and basic info."""

    tool_name = "server_init"
    description = "Test server initialization and capabilities"

    async def test(self, session) -> TestResult:
        """Test server initialization."""
        start_time = time.time()

        try:
            # The session is already initialized, but we can check the result
            # This test validates that initialization happened correctly

            # List available tools
            tools_result = await session.list_tools()

            if not tools_result.tools:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No tools returned from server",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Expected tool count (should be 12 as per CLAUDE.md)
            expected_tools = {
                "list_postgres_clusters",
                "get_cluster_status",
                "create_postgres_cluster",
                "scale_postgres_cluster",
                "delete_postgres_cluster",
                "list_postgres_roles",
                "create_postgres_role",
                "update_postgres_role",
                "delete_postgres_role",
                "list_postgres_databases",
                "create_postgres_database",
                "delete_postgres_database",
            }

            actual_tools = {tool.name for tool in tools_result.tools}
            missing_tools = expected_tools - actual_tools
            extra_tools = actual_tools - expected_tools

            if missing_tools:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Missing tools: {missing_tools}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success!
            message = f"Found {len(actual_tools)} tools"
            if extra_tools:
                message += f" (extra: {extra_tools})"

            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=message,
                duration_ms=(time.time() - start_time) * 1000
            )

        except Exception as e:
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=False,
                message="Test failed with exception",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000
            )
