"""Test plugin for create_postgres_database tool."""

import time
import asyncio
from . import TestPlugin, TestResult, check_for_operational_error, shared_test_state


class CreatePostgresDatabaseTest(TestPlugin):
    """Test the create_postgres_database tool."""

    tool_name = "create_postgres_database"
    description = "Test creating a PostgreSQL database (shared by delete test)"
    depends_on = ["CreatePostgresClusterTest"]  # Use shared test cluster
    run_after = ["ListDatabasesTest"]  # Run after baseline list

    async def test(self, session) -> TestResult:
        """Test create_postgres_database tool and store database for later tests."""
        start_time = time.time()
        db_name = f"testdb{int(time.time())}"

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

            # Create a test database
            create_result = await session.call_tool(
                self.tool_name,
                arguments={
                    "cluster_name": cluster_name,
                    "database_name": db_name,
                    "owner": "app",
                    "reclaim_policy": "delete"
                }
            )

            # Check if we got a response
            if not create_result.content:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No content in create database response",
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
                    message="Database creation failed",
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Verify database was created
            if "created successfully" not in response_text.lower() and "database" not in response_text.lower():
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Response missing expected creation confirmation",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Store database name for delete test to use
            shared_test_state["test_database_name"] = db_name

            # Success! (database will be deleted by DeletePostgresDatabaseTest)
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully created database '{db_name}' in cluster '{cluster_name}'",
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
