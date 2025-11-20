"""Test plugin to verify created role appears in list."""

import time
from . import TestPlugin, TestResult, check_for_operational_error, shared_test_state


class VerifyRoleCreatedTest(TestPlugin):
    """Verify that the created role appears in the roles list."""

    tool_name = "list_postgres_roles"
    description = "Verify created role appears in roles list"
    depends_on = ["CreatePostgresRoleTest"]  # Must run after role is created
    run_after = ["CreatePostgresRoleTest"]

    async def test(self, session) -> TestResult:
        """Verify the created role appears in list_postgres_roles output."""
        start_time = time.time()

        try:
            # Get the shared cluster and role names
            cluster_name = shared_test_state.get("test_cluster_name")
            role_name = shared_test_state.get("test_role_name")

            if not cluster_name:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No shared test cluster available",
                    error="CreatePostgresClusterTest must run first and succeed",
                    duration_ms=(time.time() - start_time) * 1000
                )

            if not role_name:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No shared test role available",
                    error="CreatePostgresRoleTest must run first and succeed",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # List roles
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

            # Verify the created role appears in the list
            if role_name not in response_text:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Created role '{role_name}' not found in roles list",
                    error=f"List output (first 500 chars): {response_text[:500]}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success!
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Verified role '{role_name}' appears in roles list for cluster '{cluster_name}'",
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
