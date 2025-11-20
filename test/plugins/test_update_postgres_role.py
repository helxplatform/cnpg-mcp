"""Test plugin for update_postgres_role tool."""

import time
import asyncio
from . import TestPlugin, TestResult, check_for_operational_error, shared_test_state


class UpdatePostgresRoleTest(TestPlugin):
    """Test the update_postgres_role tool."""

    tool_name = "update_postgres_role"
    description = "Test updating a PostgreSQL role"
    depends_on = ["CreatePostgresRoleTest"]  # Use shared test role
    run_after = ["VerifyRoleCreatedTest"]  # Run after role creation is verified

    async def test(self, session) -> TestResult:
        """Test update_postgres_role tool using the shared role."""
        start_time = time.time()

        try:
            # Use the shared test cluster and role
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

            # Update the role (enable createdb)
            update_result = await session.call_tool(
                self.tool_name,
                arguments={
                    "cluster_name": cluster_name,
                    "role_name": role_name,
                    "createdb": True
                }
            )

            # Check if we got a response
            if not update_result.content:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No content in update response",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Extract text from response
            response_text = ""
            for content in update_result.content:
                if hasattr(content, 'text'):
                    response_text += content.text

            # Check for operational errors
            is_error, error_msg = check_for_operational_error(response_text)
            if is_error:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Role update failed",
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Verify update was acknowledged
            if "updated successfully" not in response_text.lower() and "role" not in response_text.lower():
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Response missing expected update confirmation",
                    error=f"Update response: {response_text[:300]}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success! (role will be deleted by DeletePostgresRoleTest)
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully updated role '{role_name}' in cluster '{cluster_name}'",
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
