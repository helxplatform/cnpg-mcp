"""Test plugin for update_postgres_role tool."""

import time
import asyncio
from . import TestPlugin, TestResult, check_for_operational_error, shared_test_state


class UpdatePostgresRoleTest(TestPlugin):
    """Test the update_postgres_role tool."""

    tool_name = "update_postgres_role"
    description = "Test updating a PostgreSQL role"
    depends_on = ["CreatePostgresClusterTest"]  # Use shared test cluster
    run_after = ["CreatePostgresRoleTest"]  # Run after create test for logical ordering

    async def test(self, session) -> TestResult:
        """Test update_postgres_role tool."""
        start_time = time.time()
        role_name = f"test-update-role-{int(time.time())}"

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

            # Step 1: Create a role
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
                    message="Failed to create role for update test",
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Wait for role to be created
            await asyncio.sleep(3)

            # Step 2: Update the role (enable createdb)
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
                await self._cleanup_role(session, cluster_name, role_name)
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
                await self._cleanup_role(session, cluster_name, role_name)
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
                await self._cleanup_role(session, cluster_name, role_name)
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Response missing expected update confirmation",
                    error=f"Update response: {response_text[:300]}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Cleanup - delete the test role
            cleanup_success = await self._cleanup_role(session, cluster_name, role_name)

            if not cleanup_success:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Role updated successfully but cleanup failed for '{role_name}'",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success!
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully updated and cleaned up role '{role_name}' in cluster '{cluster_name}'",
                duration_ms=(time.time() - start_time) * 1000
            )

        except Exception as e:
            # Attempt cleanup even on exception
            try:
                if cluster_name:
                    await self._cleanup_role(session, cluster_name, role_name)
            except:
                pass

            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=False,
                message="Test failed with exception",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000
            )

    async def _cleanup_role(self, session, cluster_name: str, role_name: str) -> bool:
        """Helper to delete test role."""
        try:
            delete_result = await session.call_tool(
                "delete_postgres_role",
                arguments={
                    "cluster_name": cluster_name,
                    "role_name": role_name
                }
            )

            if delete_result.content:
                response_text = ""
                for content in delete_result.content:
                    if hasattr(content, 'text'):
                        response_text += content.text

                # Check if deletion succeeded
                is_error, _ = check_for_operational_error(response_text)
                return not is_error

            return False
        except Exception:
            return False
