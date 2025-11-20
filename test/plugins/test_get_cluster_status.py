"""Test plugin for get_cluster_status tool."""

import time
from . import TestPlugin, TestResult, check_for_operational_error


class GetClusterStatusTest(TestPlugin):
    """Test the get_cluster_status tool."""

    tool_name = "get_cluster_status"
    description = "Test getting cluster status details"

    async def test(self, session) -> TestResult:
        """Test get_cluster_status tool."""
        start_time = time.time()

        try:
            # First, get a cluster name from list_postgres_clusters
            list_result = await session.call_tool(
                "list_postgres_clusters",
                arguments={}
            )

            # Extract cluster name from the response
            cluster_name = None
            if list_result.content:
                response_text = ""
                for content in list_result.content:
                    if hasattr(content, 'text'):
                        response_text += content.text

                # Simple extraction - look for "test" cluster names
                if "test4" in response_text:
                    cluster_name = "test4"
                elif "test5" in response_text:
                    cluster_name = "test5"

            if not cluster_name:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No test cluster found to query status",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Call get_cluster_status
            result = await session.call_tool(
                self.tool_name,
                arguments={"name": cluster_name}
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
            if len(response_text) < 10:
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

            # Verify response contains expected status information
            if not any(keyword in response_text.lower() for keyword in ["status", "instances", "ready"]):
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Response missing expected status keywords",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success!
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully got status for cluster '{cluster_name}'",
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
