"""Tests for virtual libraries."""

from brainycat.virtual_libraries import create_virtual_library, list_virtual_libraries, delete_virtual_library


def test_module_functions_exist() -> None:
    assert callable(create_virtual_library)
    assert callable(list_virtual_libraries)
    assert callable(delete_virtual_library)


def test_create_signature() -> None:
    """create_virtual_library should accept user_id, name, query, filters."""
    import inspect
    sig = inspect.signature(create_virtual_library)
    params = list(sig.parameters.keys())
    assert "user_id" in params
    assert "name" in params
    assert "query" in params
