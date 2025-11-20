"""Test plugin for delete_postgres_database tool."""

import time
import asyncio
from . import TestPlugin, TestResult, check_for_operational_error, shared_test_state


class DeletePostgresDatabaseTest(TestPlugin):
    """Test the delete_postgres_database tool."""

    tool_name = "delete_postgres_database"
    description = "Test deleting a PostgreSQL database"
    depends_on = ["CreatePostgresClusterTest"]  # Use shared test cluster
    run_after = ["CreatePostgresDatabaseTest"]  # Run after create test for logical ordering

    async def test(self, session) -> TestResult:
        """Test delete_postgres_database tool."""
        start_time = time.time()
        database_name = f"test-delete-db-{int(time.time())}"

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

            # Step 1: Create a database to delete
            create_result = await session.call_tool(
                "create_postgres_database",
                arguments={
                    "cluster_name": cluster_name,
                    "database_name": database_name,
                    "owner": "app",
                    "reclaim_policy": "delete"
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
                    message="Failed to create database for delete test",
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Wait for database to be registered (poll up to 30 seconds)
            database_found = False
            max_wait_time = 30
            poll_interval = 3
            attempts = max_wait_time // poll_interval

            for attempt in range(attempts):
                await asyncio.sleep(poll_interval)

                try:
                    list_db_result = await session.call_tool(
                        "list_postgres_databases",
                        arguments={"cluster_name": cluster_name}
                    )

                    list_text = ""
                    if list_db_result.content:
                        for content in list_db_result.content:
                            if hasattr(content, 'text'):
                                list_text += content.text

                    if database_name in list_text:
                        database_found = True
                        break
                except Exception:
                    pass

            if not database_found:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Database '{database_name}' not found in list after creation",
                    error=f"Waited {max_wait_time} seconds but database not registered",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Step 2: Delete the database (this is what we're testing)
            delete_result = await session.call_tool(
                self.tool_name,
                arguments={
                    "cluster_name": cluster_name,
                    "database_name": database_name
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
                    message="Database deletion failed",
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Verify deletion was acknowledged
            if "deleted successfully" not in response_text.lower() and "database" not in response_text.lower():
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Response missing expected deletion confirmation",
                    error=f"Delete response: {response_text[:300]}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Step 3: Verify database is actually gone by listing databases
            # Wait a bit for deletion to propagate
            await asyncio.sleep(5)

            verify_list_result = await session.call_tool(
                "list_postgres_databases",
                arguments={"cluster_name": cluster_name}
            )

            verify_list_text = ""
            if verify_list_result.content:
                for content in verify_list_result.content:
                    if hasattr(content, 'text'):
                        verify_list_text += content.text

            # Database should not appear in the list
            if database_name in verify_list_text:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Database '{database_name}' still appears in list after deletion",
                    error=f"List output: {verify_list_text[:500]}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success!
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully deleted database '{database_name}' and verified removal in cluster '{cluster_name}'",
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
