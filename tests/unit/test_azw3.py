"""Tests for AZW3 module."""

from brainycat.azw3 import extract_azw3_cover, read_kindle_sidecar


def test_extract_cover_nonexistent() -> None:
    result = extract_azw3_cover("/nonexistent/file.azw3")
    assert result is None


def test_read_sidecar_nonexistent() -> None:
    result = read_kindle_sidecar("/nonexistent/dir.sdr")
    assert result["annotations"] == []
    assert result["position"] is None
