"""Test plugin for create_postgres_role tool."""

import time
import asyncio
from . import TestPlugin, TestResult, check_for_operational_error


class CreatePostgresRoleTest(TestPlugin):
    """Test the create_postgres_role tool with cleanup."""

    tool_name = "create_postgres_role"
    description = "Test creating and deleting a PostgreSQL role"

    async def test(self, session) -> TestResult:
        """Test create_postgres_role tool with cleanup."""
        start_time = time.time()
        role_name = f"test_role_{int(time.time())}"

        try:
            # Step 1: Get an existing cluster to use
            list_result = await session.call_tool(
                "list_postgres_clusters",
                arguments={}
            )

            cluster_name = None
            if list_result.content:
                response_text = ""
                for content in list_result.content:
                    if hasattr(content, 'text'):
                        response_text += content.text

                # Look for test clusters
                if "test4" in response_text:
                    cluster_name = "test4"
                elif "test5" in response_text:
                    cluster_name = "test5"

            if not cluster_name:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No test cluster found to create role in",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Step 2: Create a test role
            create_result = await session.call_tool(
                self.tool_name,
                arguments={
                    "cluster_name": cluster_name,
                    "role_name": role_name,
                    "login": True,
                    "superuser": False,
                    "createdb": False,
                    "createrole": False
                }
            )

            # Check if we got a response
            if not create_result.content:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No content in create role response",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Extract text from response
            response_text = ""
            for content in create_result.content:
                if hasattr(content, 'text'):
                    response_text += content.text

            # Check for operational errors
            is_error, error_msg = check_for_operational_error(response_text)
            if is_error:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Role creation failed",
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Verify role was created
            if "created successfully" not in response_text.lower() and "role" not in response_text.lower():
                await self._cleanup_role(session, cluster_name, role_name)
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Response missing expected creation confirmation",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Wait for role to be registered in Kubernetes
            await asyncio.sleep(5)

            # Step 3: Verify role exists by listing
            list_roles_result = await session.call_tool(
                "list_postgres_roles",
                arguments={"cluster_name": cluster_name}
            )

            list_text = ""
            if list_roles_result.content:
                for content in list_roles_result.content:
                    if hasattr(content, 'text'):
                        list_text += content.text

            if role_name not in list_text:
                # Try to cleanup anyway
                await self._cleanup_role(session, cluster_name, role_name)
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Created role '{role_name}' not found in role list",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Step 4: Cleanup - Delete the test role
            cleanup_success = await self._cleanup_role(session, cluster_name, role_name)

            if not cleanup_success:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Role created successfully but cleanup failed for '{role_name}'",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success!
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully created and cleaned up role '{role_name}' in cluster '{cluster_name}'",
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
                    "role_name": role_name,
                    "confirm": True
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
