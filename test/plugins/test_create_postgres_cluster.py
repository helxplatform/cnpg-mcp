"""Test plugin for create_postgres_cluster tool."""

import time
import asyncio
from . import TestPlugin, TestResult, check_for_operational_error, shared_test_state


class CreatePostgresClusterTest(TestPlugin):
    """Test the create_postgres_cluster tool. Creates a cluster for other tests to use."""

    tool_name = "create_postgres_cluster"
    description = "Test creating a PostgreSQL cluster (shared by other tests)"
    depends_on = ["ServerInfoTest"]  # Verify server responds before trying to create clusters
    run_after = ["ListClustersTest"]  # Run after baseline list

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
                    "postgres_version": "16"
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
                    error=f"Create response: {response_text[:500]}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Verify cluster creation was accepted
            if "created successfully" not in response_text.lower() and "cluster" not in response_text.lower():
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Response missing expected creation confirmation",
                    error=f"Create response: {response_text[:500]}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Immediately check if cluster was actually created (before polling)
            try:
                immediate_status = await session.call_tool(
                    "get_cluster_status",
                    arguments={"name": cluster_name}
                )

                immediate_text = ""
                if immediate_status.content:
                    for content in immediate_status.content:
                        if hasattr(content, 'text'):
                            immediate_text += content.text

                # If we get a 404 immediately, the create didn't work
                is_error, error_detail = check_for_operational_error(immediate_text)
                if is_error and "404" in immediate_text:
                    return TestResult(
                        plugin_name=self.get_name(),
                        tool_name=self.tool_name,
                        passed=False,
                        message="Cluster creation reported success but cluster not found in Kubernetes",
                        error=f"Create said: {response_text[:200]}\n\nImmediate status check: {immediate_text[:300]}",
                        duration_ms=(time.time() - start_time) * 1000
                    )
            except Exception as e:
                # Immediate check failed - this is expected, will retry with polling
                pass

            # Poll for cluster to be READY (retry up to 180 seconds / 3 minutes)
            # Initial cluster creation can take time for pod startup, image pull, DB init, etc.
            cluster_ready = False
            last_status_text = ""
            max_wait_time = 180  # seconds (3 minutes)
            poll_interval = 5  # seconds
            attempts = max_wait_time // poll_interval

            for attempt in range(attempts):
                await asyncio.sleep(poll_interval)

                try:
                    # Get cluster status
                    status_result = await session.call_tool(
                        "get_cluster_status",
                        arguments={"name": cluster_name}
                    )

                    status_text = ""
                    if status_result.content:
                        for content in status_result.content:
                            if hasattr(content, 'text'):
                                status_text += content.text

                    last_status_text = status_text

                    # Check if cluster is ready (look for "ready" or "healthy" keywords)
                    is_error, error_detail = check_for_operational_error(status_text)
                    if not is_error and len(status_text) > 10:
                        # Check if cluster shows as ready
                        status_lower = status_text.lower()
                        if "ready" in status_lower or "healthy" in status_lower:
                            cluster_ready = True
                            break
                        # Cluster exists but not ready yet - keep polling
                except Exception as e:
                    # Cluster not ready yet, continue polling
                    last_status_text = f"Exception on attempt {attempt + 1}: {str(e)}"

            if not cluster_ready:
                # Cluster didn't become ready in time - cleanup
                await self._cleanup_cluster(session, cluster_name)
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Cluster '{cluster_name}' created but not ready after {max_wait_time} seconds",
                    error=f"Last status: {last_status_text[:500]}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success! Store cluster name for other tests to use
            shared_test_state["test_cluster_name"] = cluster_name

            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully created cluster '{cluster_name}' and it is ready",
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
                    "confirm_deletion": True
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
