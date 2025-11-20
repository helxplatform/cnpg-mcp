"""Test plugin for delete_postgres_cluster tool (cleanup of shared test cluster)."""

import time
from . import TestPlugin, TestResult, check_for_operational_error, shared_test_state


class DeletePostgresClusterTest(TestPlugin):
    """Test the delete_postgres_cluster tool by cleaning up the shared test cluster."""

    tool_name = "delete_postgres_cluster"
    description = "Test deleting the shared test cluster"
    depends_on = ["CreatePostgresClusterTest"]  # Hard dependency - skip if cluster wasn't created
    run_after = [  # Soft dependencies - run after all tests that use the cluster
        "VerifyClusterCreatedTest",
        "ScalePostgresClusterTest",
        "GetClusterStatusTest",
        "ListRolesTest",
        "CreatePostgresRoleTest",
        "VerifyRoleCreatedTest",
        "UpdatePostgresRoleTest",
        "DeletePostgresRoleTest",
        "ListDatabasesTest",
        "CreatePostgresDatabaseTest",
        "VerifyDatabaseCreatedTest",
        "DeletePostgresDatabaseTest"
    ]

    async def test(self, session) -> TestResult:
        """Delete the shared test cluster."""
        start_time = time.time()

        try:
            # Get the shared cluster name
            cluster_name = shared_test_state.get("test_cluster_name")

            if not cluster_name:
                # No cluster to clean up - this is okay
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=True,
                    message="No shared test cluster to clean up",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Delete the cluster
            delete_result = await session.call_tool(
                self.tool_name,
                arguments={
                    "name": cluster_name,
                    "confirm_deletion": True
                }
            )

            # Check if we got a response
            if not delete_result.content:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"No content in delete response for cluster '{cluster_name}'",
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
                    message=f"Failed to delete cluster '{cluster_name}'",
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success - clear the shared state
            shared_test_state["test_cluster_name"] = None

            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully deleted shared test cluster '{cluster_name}'",
                duration_ms=(time.time() - start_time) * 1000
            )

        except Exception as e:
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=False,
                message="Cluster deletion test failed with exception",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000
            )
