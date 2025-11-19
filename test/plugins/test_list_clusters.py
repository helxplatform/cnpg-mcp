"""Test plugin for list_postgres_clusters tool."""

import time
from . import TestPlugin, TestResult, check_for_operational_error


class ListClustersTest(TestPlugin):
    """Test the list_postgres_clusters tool."""

    tool_name = "list_postgres_clusters"
    description = "Test listing PostgreSQL clusters"

    async def test(self, session) -> TestResult:
        """Test list_postgres_clusters tool."""
        start_time = time.time()

        try:
            # Call the tool
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

            # Basic validation - should have some text
            if len(response_text) < 10:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Response too short ({len(response_text)} chars)",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Check for operational errors (e.g., RBAC issues, connection failures)
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

            # Success!
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully listed clusters ({len(response_text)} chars)",
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
