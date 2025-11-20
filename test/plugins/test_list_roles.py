"""Test plugin for list_postgres_roles tool."""

import time
from . import TestPlugin, TestResult, check_for_operational_error, shared_test_state


class ListRolesTest(TestPlugin):
    """Test the list_postgres_roles tool."""

    tool_name = "list_postgres_roles"
    description = "Test listing PostgreSQL roles/users"
    depends_on = ["CreatePostgresClusterTest"]  # Use shared test cluster

    async def test(self, session) -> TestResult:
        """Test list_postgres_roles tool."""
        start_time = time.time()

        try:
            # Use the shared test cluster
            cluster_name = shared_test_state.get("test_cluster_name")

            if not cluster_name:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No shared test cluster available",
                    error="CreatePostgresClusterTest must run first and succeed",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Call list_postgres_roles
            result = await session.call_tool(
                self.tool_name,
                arguments={"cluster_name": cluster_name}
            )

            # Check if we got a response
            if not result.content:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No content in response",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Extract text from response
            response_text = ""
            for content in result.content:
                if hasattr(content, 'text'):
                    response_text += content.text

            # Basic validation
            if len(response_text) < 5:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Response too short ({len(response_text)} chars)",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Check for operational errors
            is_error, error_msg = check_for_operational_error(response_text)
            if is_error:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Tool executed but operation failed",
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success! (even if no roles found, that's a valid response)
            role_count = response_text.lower().count("role:")
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully listed roles for '{cluster_name}' ({role_count} roles)",
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
