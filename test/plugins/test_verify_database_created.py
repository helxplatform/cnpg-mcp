"""Test plugin to verify created database appears in list."""

import time
import asyncio
from . import TestPlugin, TestResult, check_for_operational_error, shared_test_state


class VerifyDatabaseCreatedTest(TestPlugin):
    """Verify that the created database appears in the databases list."""

    tool_name = "list_postgres_databases"
    description = "Verify created database appears in databases list"
    depends_on = ["CreatePostgresDatabaseTest"]  # Must run after database is created
    run_after = ["CreatePostgresDatabaseTest"]

    async def test(self, session) -> TestResult:
        """Verify the created database appears in list_postgres_databases output."""
        start_time = time.time()

        try:
            # Get the shared cluster and database names
            cluster_name = shared_test_state.get("test_cluster_name")
            database_name = shared_test_state.get("test_database_name")

            if not cluster_name:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No shared test cluster available",
                    error="CreatePostgresClusterTest must run first and succeed",
                    duration_ms=(time.time() - start_time) * 1000
                )

            if not database_name:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No shared test database available",
                    error="CreatePostgresDatabaseTest must run first and succeed",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Poll for database to appear in list (retry up to 30 seconds)
            # Database creation can take time to propagate in Kubernetes
            database_found = False
            last_list_text = ""
            max_wait_time = 30  # seconds
            poll_interval = 3  # seconds
            attempts = max_wait_time // poll_interval

            for attempt in range(attempts):
                await asyncio.sleep(poll_interval)

                try:
                    # List databases
                    result = await session.call_tool(
                        self.tool_name,
                        arguments={"cluster_name": cluster_name}
                    )

                    # Extract text from response
                    response_text = ""
                    if result.content:
                        for content in result.content:
                            if hasattr(content, 'text'):
                                response_text += content.text

                    last_list_text = response_text

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

                    # Check if database appears in list
                    if database_name in response_text:
                        database_found = True
                        break
                except Exception as e:
                    last_list_text = f"Exception on attempt {attempt + 1}: {str(e)}"

            if not database_found:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Created database '{database_name}' not found in databases list after {max_wait_time} seconds",
                    error=f"Last list output (first 500 chars): {last_list_text[:500]}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success!
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Verified database '{database_name}' appears in databases list for cluster '{cluster_name}'",
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
