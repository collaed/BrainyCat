"""Tests for MCP server tool definitions."""

import json


def test_mcp_server_imports() -> None:
    from brainycat.mcp_server import app, list_tools
    assert app is not None
    assert callable(list_tools)


def test_mcp_tool_count() -> None:
    """Verify we have the expected number of MCP tools."""
    import asyncio
    from brainycat.mcp_server import list_tools
    tools = asyncio.get_event_loop().run_until_complete(list_tools())
    assert len(tools) >= 20  # We have 23 tools


def test_mcp_tool_schemas_valid() -> None:
    """All tools should have valid JSON Schema input definitions."""
    import asyncio
    from brainycat.mcp_server import list_tools
    tools = asyncio.get_event_loop().run_until_complete(list_tools())
    for tool in tools:
        assert tool.name, "Tool must have a name"
        assert tool.description, f"Tool {tool.name} must have a description"
        schema = tool.inputSchema
        assert schema.get("type") == "object", f"Tool {tool.name} schema must be object type"
        assert "properties" in schema, f"Tool {tool.name} must have properties"
