"""Test plugin for create_postgres_role tool."""

import time
import asyncio
from . import TestPlugin, TestResult, check_for_operational_error, shared_test_state


class CreatePostgresRoleTest(TestPlugin):
    """Test the create_postgres_role tool."""

    tool_name = "create_postgres_role"
    description = "Test creating a PostgreSQL role (shared by update/delete tests)"
    depends_on = ["CreatePostgresClusterTest"]  # Use shared test cluster
    run_after = ["ListRolesTest"]  # Run after baseline list

    async def test(self, session) -> TestResult:
        """Test create_postgres_role tool and store role for later tests."""
        start_time = time.time()
        # Use hyphens instead of underscores for Kubernetes-compliant naming
        role_name = f"test-role-{int(time.time())}"

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

            # Create a test role
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
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Response missing expected creation confirmation",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Wait for role to be registered in Kubernetes
            await asyncio.sleep(3)

            # Store role name for update and delete tests to use
            shared_test_state["test_role_name"] = role_name

            # Success! (role will be deleted by DeletePostgresRoleTest)
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully created role '{role_name}' in cluster '{cluster_name}'",
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
