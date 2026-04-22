"""Tests for EPUB merge/split tools."""
import pytest

def test_module_exists() -> None:
    import importlib
    spec = importlib.util.find_spec("brainycat.epub_tools")
    assert spec is not None
