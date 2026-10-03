"""Tests for brainycat.file_hashes (K6 — original-bytes hashing + Anna's Archive MD5)."""

import hashlib
import os
import tempfile

from brainycat.file_hashes import anna_md5_from_name, capture_original_hashes, md5_file, sha256_file


def _tmp(content: bytes) -> str:
    fd, path = tempfile.mkstemp()
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return path


def test_md5_and_sha256_match_hashlib() -> None:
    path = _tmp(b"hello brainycat")
    try:
        assert md5_file(path) == hashlib.md5(b"hello brainycat").hexdigest()
        assert sha256_file(path) == hashlib.sha256(b"hello brainycat").hexdigest()
    finally:
        os.unlink(path)


def test_hash_missing_file_returns_none() -> None:
    assert md5_file("/nonexistent/xyz") is None
    assert sha256_file("/nonexistent/xyz") is None


def test_anna_md5_from_annas_archive_filename() -> None:
    name = ("21b50b4d Autism Your Questions Answered -- Romeo Vitelli -- 1, 2024 -- "
            "Bloomsbury -- 9781440881565 -- 1e9c3d90f7395ba6b878c4b76e431e7a -- Anna's Archive.epub")
    assert anna_md5_from_name(name) == "1e9c3d90f7395ba6b878c4b76e431e7a"


def test_anna_md5_prefers_token_next_to_marker() -> None:
    # A leading 8-hex prefix must not be mistaken for the 32-hex MD5.
    name = "c1889e12 Goddess -- K D West -- 2d3857477610acb4828a9e1828fabc27 -- Anna's Archive.epub"
    assert anna_md5_from_name(name) == "2d3857477610acb4828a9e1828fabc27"


def test_anna_md5_absent_returns_none() -> None:
    assert anna_md5_from_name("Just A Normal Title.epub") is None


def test_capture_original_hashes_shape() -> None:
    path = _tmp(b"content")
    try:
        h = capture_original_hashes(path, "x -- 1e9c3d90f7395ba6b878c4b76e431e7a -- Anna's Archive.epub")
        assert set(h) == {"original_md5", "original_sha256", "anna_md5"}
        assert h["original_md5"] == hashlib.md5(b"content").hexdigest()
        assert h["anna_md5"] == "1e9c3d90f7395ba6b878c4b76e431e7a"
    finally:
        os.unlink(path)
