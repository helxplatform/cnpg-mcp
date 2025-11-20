"""Test plugin for scale_postgres_cluster tool."""

import time
import asyncio
from . import TestPlugin, TestResult, check_for_operational_error, shared_test_state


class ScalePostgresClusterTest(TestPlugin):
    """Test the scale_postgres_cluster tool using the shared test cluster."""

    tool_name = "scale_postgres_cluster"
    description = "Test scaling a PostgreSQL cluster"
    depends_on = ["CreatePostgresClusterTest"]  # Depends on cluster creation

    async def test(self, session) -> TestResult:
        """Test scale_postgres_cluster tool using shared cluster."""
        start_time = time.time()

        try:
            # Use the cluster created by CreatePostgresClusterTest
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

            # Get initial instance count
            initial_status = await session.call_tool(
                "get_cluster_status",
                arguments={"name": cluster_name}
            )

            # Scale cluster from 1 to 2 instances
            scale_result = await session.call_tool(
                self.tool_name,
                arguments={
                    "name": cluster_name,
                    "instances": 2
                }
            )

            # Check if we got a response
            if not scale_result.content:
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
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Cluster scaling failed",
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Verify scaling was initiated
            response_lower = response_text.lower()
            if "scaling" not in response_lower and "scale" not in response_lower:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message="Response missing expected scaling confirmation",
                    error=f"Scale response: {response_text[:300]}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Poll for scaling to complete (wait up to 60 seconds)
            scaling_complete = False
            last_status_text = ""
            max_wait_time = 60  # seconds
            poll_interval = 3  # seconds
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

                    # Check if scaling is complete by looking for instance count
                    # The status should show 2 instances (or 2/2 ready)
                    status_lower = status_text.lower()
                    if ("2 instances" in status_lower or
                        "instances: 2" in status_lower or
                        "2/2" in status_text or
                        ("ready instances: 2" in status_lower)):
                        scaling_complete = True
                        break
                except Exception as e:
                    last_status_text = f"Exception on attempt {attempt + 1}: {str(e)}"

            if not scaling_complete:
                return TestResult(
                    plugin_name=self.get_name(),
                    tool_name=self.tool_name,
                    passed=False,
                    message=f"Scaling initiated but not complete after {max_wait_time} seconds",
                    error=f"Last status: {last_status_text[:500]}",
                    duration_ms=(time.time() - start_time) * 1000
                )

            # Success!
            return TestResult(
                plugin_name=self.get_name(),
                tool_name=self.tool_name,
                passed=True,
                message=f"Successfully scaled cluster '{cluster_name}' from 1 to 2 instances",
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
