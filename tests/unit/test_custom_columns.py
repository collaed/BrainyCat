"""Tests for custom columns module."""

from brainycat.custom_columns import create_column, list_columns, set_value, get_value


def test_module_callable() -> None:
    assert callable(create_column)
    assert callable(list_columns)
    assert callable(set_value)
    assert callable(get_value)
