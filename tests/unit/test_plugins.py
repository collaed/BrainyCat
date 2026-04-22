"""Tests for plugin system."""

from brainycat.plugins import BrainyCatPlugin, discover_plugins, get_plugins


def test_base_plugin() -> None:
    p = BrainyCatPlugin()
    assert p.name == "unnamed"
    p.on_upload("test", {})  # Should not raise
    p.on_enrich("test", "source", {})
    p.on_schedule()


def test_discover_nonexistent() -> None:
    result = discover_plugins("/nonexistent/path")
    assert result == []


def test_get_plugins_empty() -> None:
    plugins = get_plugins()
    assert isinstance(plugins, list)
