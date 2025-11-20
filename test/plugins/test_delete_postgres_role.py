"""Test plugin for delete_postgres_role tool."""

import time
import asyncio
from . import TestPlugin, TestResult, check_for_operational_error, shared_test_state


class DeletePostgresRoleTest(TestPlugin):
    """Test the delete_postgres_role tool."""

    tool_name = "delete_postgres_role"
    description = "Test deleting a PostgreSQL role"
    depends_on = ["CreatePostgresClusterTest"]  # Use shared test cluster
    run_after = ["CreatePostgresRoleTest", "UpdatePostgresRoleTest"]  # Run after create/update for logical ordering

    async def test(self, session) -> TestResult:
        """Test delete_postgres_role tool."""
        start_time = time.time()
        role_name = f"test-delete-role-{int(time.time())}"

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

            # Step 1: Create a role to delete
            create_result = await session.call_tool(
                "create_postgres_role",
                arguments={
                    "cluster_name": cluster_name,
                    "role_name": role_name,
                    "login": True,
                    "superuser": False,
                    "createdb": False,
                    "createrole": False
                }
            )

            # Check creation success
            create_text = ""
            if create_result.content:
                for content in create_result.content:
                    if hasattr(content, 'text'):
                        create_text += content.text

            is_error, error_msg = check_for_operational_error(create_text)
            if is_error:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Failed to create role for delete test",
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Wait for role to be created
            await asyncio.sleep(3)

            # Step 2: Delete the role (this is what we're testing)
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
