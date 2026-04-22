"""Tests for OPDS feed."""

from brainycat.opds import _esc


def test_esc_ampersand() -> None:
    assert _esc("A & B") == "A &amp; B"


def test_esc_angle_brackets() -> None:
    assert _esc("<tag>") == "&lt;tag&gt;"


def test_esc_clean() -> None:
    assert _esc("normal text") == "normal text"


def test_esc_empty() -> None:
    assert _esc("") == ""
