"""Tests for virtual libraries module."""

from brainycat.virtual_libraries import create_virtual_library, list_virtual_libraries


def test_module_callable() -> None:
    assert callable(create_virtual_library)
    assert callable(list_virtual_libraries)
