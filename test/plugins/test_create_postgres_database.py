"""Test plugin for create_postgres_database tool."""

import time
import asyncio
from . import TestPlugin, TestResult, check_for_operational_error


class CreatePostgresDatabaseTest(TestPlugin):
    """Test the create_postgres_database tool with cleanup."""

    tool_name = "create_postgres_database"
    description = "Test creating and deleting a PostgreSQL database"

    async def test(self, session) -> TestResult:
        """Test create_postgres_database tool with cleanup."""
        start_time = time.time()
        db_name = f"testdb{int(time.time())}"

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
                    message="No test cluster found to create database in",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Step 2: Create a test database
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
                await self._cleanup_database(session, db_name)
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Response missing expected creation confirmation",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Wait for database to be registered in Kubernetes
            await asyncio.sleep(5)

            # Step 3: Verify database exists by listing
            list_db_result = await session.call_tool(
                "list_postgres_databases",
                arguments={}
            )

            list_text = ""
            if list_db_result.content:
                for content in list_db_result.content:
                    if hasattr(content, 'text'):
                        list_text += content.text

            if db_name not in list_text:
                # Try to cleanup anyway
                await self._cleanup_database(session, db_name)
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Created database '{db_name}' not found in database list",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Step 4: Cleanup - Delete the test database
            cleanup_success = await self._cleanup_database(session, db_name)

            if not cleanup_success:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Database created successfully but cleanup failed for '{db_name}'",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success!
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully created and cleaned up database '{db_name}' in cluster '{cluster_name}'",
                duration_ms=(time.time() - start_time) * 1000
            )

        except Exception as e:
            # Attempt cleanup even on exception
            try:
                await self._cleanup_database(session, db_name)
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

    async def _cleanup_database(self, session, database_name: str) -> bool:
        """Helper to delete test database."""
        try:
            delete_result = await session.call_tool(
                "delete_postgres_database",
                arguments={
                    "database_name": database_name,
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
