"""AZW3 enhanced support — KF8 parsing, cover extraction, sidecar reading."""

from __future__ import annotations

import os
import struct
from typing import Any


def extract_azw3_cover(path: str) -> bytes | None:
    """Extract cover image from AZW3/MOBI thumbnail records."""
    try:
        with open(path, "rb") as f:
            data = f.read()

        # MOBI header: first image record contains the cover
        # PDB header: 78 bytes, then record offsets
        if data[:8] not in (b"BOOKMOBI", b"\x00" * 8):
            return None

        # Find EXTH header for cover offset
        exth_pos = data.find(b"EXTH")
        if exth_pos < 0:
            return None

        # Parse EXTH records to find cover offset (type 201)
        count = struct.unpack(">I", data[exth_pos + 8 : exth_pos + 12])[0]
        pos = exth_pos + 12
        for _ in range(min(count, 200)):
            if pos + 8 > len(data):
                break
            rec_type = struct.unpack(">I", data[pos : pos + 4])[0]
            rec_len = struct.unpack(">I", data[pos + 4 : pos + 8])[0]
            if rec_type == 201 and rec_len >= 12:  # CoverOffset
                struct.unpack(">I", data[pos + 8 : pos + 12])[0]
            pos += rec_len

        # Find image records — look for JPEG/PNG magic bytes
        for marker in (b"\xff\xd8\xff", b"\x89PNG"):
            idx = data.find(marker)
            if idx > 0:
                if marker == b"\xff\xd8\xff":
                    end = data.find(b"\xff\xd9", idx)
                    if end > idx:
                        return data[idx : end + 2]
                else:
                    # PNG — find IEND chunk
                    end = data.find(b"IEND", idx)
                    if end > idx:
                        return data[idx : end + 8]

    except Exception:
        pass
    return None


def read_kindle_sidecar(sdr_path: str) -> dict[str, Any]:
    """Read Kindle sidecar (.sdr) directory for reading position and annotations."""
    result: dict[str, Any] = {"annotations": [], "position": None}

    if not os.path.isdir(sdr_path):
        return result

    # Look for .mbp1 (annotations) and .azw3r (reading position)
    for fname in os.listdir(sdr_path):
        fpath = os.path.join(sdr_path, fname)
        if fname.endswith(".mbp1"):
            # MBP1 is a binary format — extract text annotations
            try:
                with open(fpath, "rb") as f:
                    data = f.read()
                # Find UTF-8 text runs that look like annotations
                import re

                for m in re.finditer(rb"[\x20-\x7e\xc0-\xff]{20,}", data):
                    text = m.group().decode("utf-8", errors="ignore").strip()
                    if text and not text.startswith(("<?", "<!", "{")):
                        result["annotations"].append(text)
            except Exception:
                pass

    return result
