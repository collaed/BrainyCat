"""Atomic file writes — temp file + rename to prevent corruption.

Use atomic_write() anywhere we write files that must not be half-written:
covers, metadata writeback, conversions, EPUB modifications.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator


@contextmanager
def atomic_write(target: str, mode: str = "wb") -> Generator:
    """Write to a temp file, rename to target on success. Clean up on failure.

    Usage:
        with atomic_write("/data/covers/book.jpg") as f:
            f.write(image_data)
        # File only appears at target path if write succeeds
    """
    dir_name = os.path.dirname(target) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".tmp_", suffix=os.path.splitext(target)[1])
    try:
        with os.fdopen(fd, mode) as f:
            yield f
        os.rename(tmp_path, target)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp_path)
        raise
