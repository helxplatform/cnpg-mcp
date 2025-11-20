"""Test plugin to verify created cluster appears in list."""

import time
from . import TestPlugin, TestResult, check_for_operational_error, shared_test_state


class VerifyClusterCreatedTest(TestPlugin):
    """Verify that the created cluster appears in the clusters list."""

    tool_name = "list_postgres_clusters"
    description = "Verify created cluster appears in clusters list"
    depends_on = ["CreatePostgresClusterTest"]  # Must run after cluster is created
    run_after = ["CreatePostgresClusterTest"]

    async def test(self, session) -> TestResult:
        """Verify the created cluster appears in list_postgres_clusters output."""
        start_time = time.time()

        try:
            # Get the shared cluster name
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

            # List clusters
            result = await session.call_tool(
                self.tool_name,
                arguments={}
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

            # Verify the created cluster appears in the list
            if cluster_name not in response_text:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Created cluster '{cluster_name}' not found in clusters list",
                    error=f"List output (first 500 chars): {response_text[:500]}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success!
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Verified cluster '{cluster_name}' appears in clusters list",
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
