"""
MCP Test Plugin System

Plugins are Python modules that test individual MCP tools.
Each plugin should inherit from TestPlugin and implement the test() method.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TestResult:
    """Result of a test plugin execution."""
    plugin_name: str
    tool_name: str
    passed: bool
    message: str
    error: Optional[str] = None
    duration_ms: Optional[float] = None


class TestPlugin:
    """Base class for MCP test plugins."""

    # Override these in your plugin
    tool_name: str = "unknown"
    description: str = "No description"

    async def test(self, session) -> TestResult:
        """
        Run the test for this tool.

        Args:
            session: MCP ClientSession instance

        Returns:
            TestResult with pass/fail status and details
        """
        raise NotImplementedError("Plugin must implement test() method")

    def get_name(self) -> str:
        """Get the plugin name (defaults to class name)."""
        return self.__class__.__name__
