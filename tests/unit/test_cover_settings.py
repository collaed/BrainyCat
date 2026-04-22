"""Tests for cover settings."""

from brainycat.cover_settings import DEFAULTS


def test_defaults_complete() -> None:
    assert "fiction_stripe" in DEFAULTS
    assert "nonfiction_stripe" in DEFAULTS
    assert "font_family" in DEFAULTS
    assert "show_author" in DEFAULTS
    assert "background_style" in DEFAULTS


def test_defaults_values() -> None:
    assert DEFAULTS["fiction_stripe"] == "vertical"
    assert DEFAULTS["nonfiction_stripe"] == "horizontal"
    assert DEFAULTS["show_author"] is True
