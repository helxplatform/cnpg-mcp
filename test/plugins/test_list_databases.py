"""Test plugin for list_postgres_databases tool."""

import time
from . import TestPlugin, TestResult, check_for_operational_error


class ListDatabasesTest(TestPlugin):
    """Test the list_postgres_databases tool."""

    tool_name = "list_postgres_databases"
    description = "Test listing PostgreSQL databases"

    async def test(self, session) -> TestResult:
        """Test list_postgres_databases tool."""
        start_time = time.time()

        try:
            # Call list_postgres_databases (no cluster name needed - lists all Database CRDs)
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

            # Basic validation
            if len(response_text) < 5:
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

            # Success! (even if no databases found, that's a valid response)
            if "No databases found" in response_text or "database" in response_text.lower():
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=True,
                    message=f"Successfully listed databases ({len(response_text)} chars)",
                    duration_ms=(time.time() - start_time) * 1000
                )
            else:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Response missing expected database information",
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
