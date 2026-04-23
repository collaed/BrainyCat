"""Tests for atomic file writes."""

import os
import tempfile

import pytest

from brainycat.atomic import atomic_write


def test_atomic_write_success() -> None:
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "test.txt")
        with atomic_write(target, "w") as f:
            f.write("hello")
        assert os.path.isfile(target)
        assert open(target).read() == "hello"


def test_atomic_write_binary() -> None:
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "test.bin")
        with atomic_write(target) as f:
            f.write(b"\xff\xd8\xff")
        assert open(target, "rb").read() == b"\xff\xd8\xff"


def test_atomic_write_failure_no_partial() -> None:
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "test.txt")
        with pytest.raises(ValueError):
            with atomic_write(target, "w") as f:
                f.write("partial")
                raise ValueError("simulated crash")
        # Target should NOT exist — write failed
        assert not os.path.isfile(target)


def test_atomic_write_no_overwrite_on_failure() -> None:
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "existing.txt")
        with open(target, "w") as f:
            f.write("original")
        with pytest.raises(ValueError):
            with atomic_write(target, "w") as f:
                f.write("replacement")
                raise ValueError("crash")
        # Original should be untouched
        assert open(target).read() == "original"


def test_atomic_write_no_temp_files_left() -> None:
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "test.txt")
        with atomic_write(target, "w") as f:
            f.write("data")
        # No .tmp files should remain
        files = os.listdir(d)
        assert files == ["test.txt"]
