"""Tests for custom columns — type validation, search, CRUD."""

from brainycat.custom_columns import _validate_value, VALID_TYPES


def test_valid_types() -> None:
    assert "text" in VALID_TYPES
    assert "number" in VALID_TYPES
    assert "date" in VALID_TYPES
    assert "boolean" in VALID_TYPES
    assert "rating" in VALID_TYPES
    assert "tags" in VALID_TYPES


def test_validate_text() -> None:
    val, err = _validate_value("hello", "text")
    assert val == "hello"
    assert err is None


def test_validate_number() -> None:
    val, err = _validate_value(42, "number")
    assert val == 42.0
    assert err is None

    val, err = _validate_value("3.14", "number")
    assert val == 3.14

    val, err = _validate_value("not a number", "number")
    assert err is not None


def test_validate_boolean() -> None:
    val, err = _validate_value(True, "boolean")
    assert val is True

    val, err = _validate_value("yes", "boolean")
    assert val is True

    val, err = _validate_value("false", "boolean")
    assert val is False

    val, err = _validate_value("maybe", "boolean")
    assert err is not None


def test_validate_rating() -> None:
    val, err = _validate_value(8.5, "rating")
    assert val == 8.5
    assert err is None

    val, err = _validate_value(11, "rating")
    assert err is not None  # Out of range

    val, err = _validate_value(-1, "rating")
    assert err is not None


def test_validate_date() -> None:
    val, err = _validate_value("2024-03-15", "date")
    assert val == "2024-03-15"
    assert err is None

    val, err = _validate_value("not-a-date", "date")
    assert err is not None


def test_validate_tags() -> None:
    val, err = _validate_value("sci-fi, fantasy, horror", "tags")
    assert val == ["sci-fi", "fantasy", "horror"]
    assert err is None

    val, err = _validate_value(["a", "b"], "tags")
    assert val == ["a", "b"]


def test_validate_none() -> None:
    val, err = _validate_value(None, "text")
    assert val is None
    assert err is None


def test_validate_unknown_type() -> None:
    val, err = _validate_value("x", "unknown_type")
    assert err is not None
