"""
MCP Test Plugin System

Plugins are Python modules that test individual MCP tools.
Each plugin should inherit from TestPlugin and implement the test() method.
"""

from dataclasses import dataclass
from typing import Optional, Tuple
import re


@dataclass
class TestResult:
    """Result of a test plugin execution."""
    plugin_name: str
    tool_name: str
    passed: bool
    message: str
    error: Optional[str] = None
    duration_ms: Optional[float] = None


def check_for_operational_error(response_text: str) -> Tuple[bool, Optional[str]]:
    """
    Check if a tool response contains an operational error.

    MCP tools may execute successfully (no exception) but return error messages
    indicating the underlying operation failed (e.g., RBAC permissions, network issues).

    Args:
        response_text: The text content returned by the MCP tool

    Returns:
        Tuple of (is_error, error_message)
        - is_error: True if response contains an error
        - error_message: Extracted error message if found, None otherwise
    """
    # Error patterns that indicate operational failures
    error_patterns = [
        r'Error (?:listing|getting|creating|updating|deleting|scaling)',
        r'Kubernetes API Error',
        r'\d{3} Forbidden',
        r'is forbidden:',
        r'cannot (?:list|get|create|update|delete|patch) resource',
        r'Permission denied',
        r'Unauthorized',
        r'Authentication failed',
        r'Connection refused',
        r'Connection timeout',
        r'No route to host',
    ]

    for pattern in error_patterns:
        match = re.search(pattern, response_text, re.IGNORECASE)
        if match:
            # Extract error context (up to 500 chars from the match)
            start = max(0, match.start() - 50)
            end = min(len(response_text), match.end() + 450)
            error_context = response_text[start:end].strip()

            # Clean up the error message
            # Remove excessive whitespace and newlines
            error_context = re.sub(r'\s+', ' ', error_context)

            return True, error_context

    return False, None


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
