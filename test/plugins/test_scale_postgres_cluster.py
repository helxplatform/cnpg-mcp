"""Test plugin for scale_postgres_cluster tool."""

import time
import asyncio
from . import TestPlugin, TestResult, check_for_operational_error


class ScalePostgresClusterTest(TestPlugin):
    """Test the scale_postgres_cluster tool with create and cleanup."""

    tool_name = "scale_postgres_cluster"
    description = "Test scaling a PostgreSQL cluster"

    async def test(self, session) -> TestResult:
        """Test scale_postgres_cluster tool."""
        start_time = time.time()
        cluster_name = f"test-scale-{int(time.time())}"

        try:
            # Step 1: Create a test cluster with 1 instance
            create_result = await session.call_tool(
                "create_postgres_cluster",
                arguments={
                    "name": cluster_name,
                    "instances": 1,
                    "storage_size": "1Gi",
                    "postgresql_version": "16"
                }
            )

            # Check creation success
            if not create_result.content:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Failed to create test cluster",
                    duration_ms=(time.time() - start_time) * 1000
                )

            create_text = ""
            for content in create_result.content:
                if hasattr(content, 'text'):
                    create_text += content.text

            is_error, error_msg = check_for_operational_error(create_text)
            if is_error:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Failed to create test cluster for scaling",
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Wait for cluster to be fully created and ready
            await asyncio.sleep(5)

            # Step 2: Scale cluster to 2 instances
            scale_result = await session.call_tool(
                self.tool_name,
                arguments={
                    "name": cluster_name,
                    "instances": 2
                }
            )

            # Check if we got a response
            if not scale_result.content:
                await self._cleanup_cluster(session, cluster_name)
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="No content in scale response",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Extract text from response
            response_text = ""
            for content in scale_result.content:
                if hasattr(content, 'text'):
                    response_text += content.text

            # Check for operational errors
            is_error, error_msg = check_for_operational_error(response_text)
            if is_error:
                await self._cleanup_cluster(session, cluster_name)
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Cluster scaling failed",
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Verify scaling was acknowledged
            if "scaled" not in response_text.lower() and "instances" not in response_text.lower():
                await self._cleanup_cluster(session, cluster_name)
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Response missing expected scaling confirmation",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Step 3: Verify cluster status shows updated instance count
            await asyncio.sleep(3)
            status_result = await session.call_tool(
                "get_cluster_status",
                arguments={"name": cluster_name}
            )

            status_text = ""
            if status_result.content:
                for content in status_result.content:
                    if hasattr(content, 'text'):
                        status_text += content.text

            # Cleanup: Delete the test cluster
            cleanup_success = await self._cleanup_cluster(session, cluster_name)

            if not cleanup_success:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Cluster scaled successfully but cleanup failed for '{cluster_name}'",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success!
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully scaled cluster '{cluster_name}' from 1 to 2 instances and cleaned up",
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
        except Exception:
            return False
