"""Test plugin for delete_postgres_role tool."""

import time
import asyncio
from . import TestPlugin, TestResult, check_for_operational_error, shared_test_state


class DeletePostgresRoleTest(TestPlugin):
    """Test the delete_postgres_role tool."""

    tool_name = "delete_postgres_role"
    description = "Test deleting a PostgreSQL role"
    depends_on = ["CreatePostgresRoleTest"]  # Use shared test role
    run_after = ["UpdatePostgresRoleTest"]  # Run after update test for logical ordering

    async def test(self, session) -> TestResult:
        """Test delete_postgres_role tool using the shared role."""
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

            # Delete the role (this is what we're testing)
            delete_result = await session.call_tool(
                self.tool_name,
                arguments={
                    "cluster_name": cluster_name,
                    "role_name": role_name
                }
            )

            # Check if we got a response
            if not delete_result.content:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No content in delete response",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Extract text from response
            response_text = ""
            for content in delete_result.content:
                if hasattr(content, 'text'):
                    response_text += content.text

            # Check for operational errors
            is_error, error_msg = check_for_operational_error(response_text)
            if is_error:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Role deletion failed",
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Verify deletion was acknowledged
            if "deleted successfully" not in response_text.lower() and "role" not in response_text.lower():
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Response missing expected deletion confirmation",
                    error=f"Delete response: {response_text[:300]}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Step 3: Verify role is actually gone by listing roles
            await asyncio.sleep(2)
            list_result = await session.call_tool(
                "list_postgres_roles",
                arguments={"cluster_name": cluster_name}
            )

            list_text = ""
            if list_result.content:
                for content in list_result.content:
                    if hasattr(content, 'text'):
                        list_text += content.text

            # Role should not appear in the list
            if role_name in list_text:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Role '{role_name}' still appears in list after deletion",
                    error=f"List output: {list_text[:500]}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success!
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully deleted role '{role_name}' and verified removal in cluster '{cluster_name}'",
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
