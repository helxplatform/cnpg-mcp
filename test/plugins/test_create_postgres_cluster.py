"""Test plugin for create_postgres_cluster tool."""

import time
from . import TestPlugin, TestResult, check_for_operational_error


class CreatePostgresClusterTest(TestPlugin):
    """Test the create_postgres_cluster tool with cleanup."""

    tool_name = "create_postgres_cluster"
    description = "Test creating and deleting a PostgreSQL cluster"

    async def test(self, session) -> TestResult:
        """Test create_postgres_cluster tool with cleanup."""
        start_time = time.time()
        cluster_name = f"test-cluster-{int(time.time())}"

        try:
            # Create a minimal test cluster
            create_result = await session.call_tool(
                self.tool_name,
                arguments={
                    "name": cluster_name,
                    "instances": 1,
                    "storage_size": "1Gi",
                    "postgresql_version": "16"
                }
            )

            # Check if we got a response
            if not create_result.content:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No content in create response",
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
                    message="Cluster creation failed",
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Verify cluster was created
            if "created successfully" not in response_text.lower() and "cluster" not in response_text.lower():
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Response missing expected creation confirmation",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Wait for cluster to be registered in Kubernetes
            await asyncio.sleep(5)

            # Verify cluster exists by listing
            list_result = await session.call_tool(
                "list_postgres_clusters",
                arguments={}
            )

            list_text = ""
            if list_result.content:
                for content in list_result.content:
                    if hasattr(content, 'text'):
                        list_text += content.text

            if cluster_name not in list_text:
                # Try to cleanup anyway
                await self._cleanup_cluster(session, cluster_name)
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Created cluster '{cluster_name}' not found in list",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Cleanup: Delete the test cluster
            cleanup_success = await self._cleanup_cluster(session, cluster_name)

            if not cleanup_success:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Cluster created successfully but cleanup failed for '{cluster_name}'",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success!
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully created and cleaned up cluster '{cluster_name}'",
                duration_ms=(time.time() - start_time) * 1000
            )

        except Exception as e:
            # Attempt cleanup even on exception
            try:
                await self._cleanup_cluster(session, cluster_name)
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

    async def _cleanup_cluster(self, session, cluster_name: str) -> bool:
        """Helper to delete test cluster."""
        try:
            delete_result = await session.call_tool(
                "delete_postgres_cluster",
                arguments={
                    "name": cluster_name,
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
        except Exception as e:
            return False


import asyncio
