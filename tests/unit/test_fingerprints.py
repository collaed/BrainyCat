"""Tests for fingerprinting."""

import subprocess
import sys
from pathlib import Path

from brainycat.fingerprints import (
    _extract_full_text,
    _jaccard_minhash,
    _kgram_hashes,
    _minhash,
    _normalize,
    _structural_fingerprint,
    _text_fingerprint,
    _winnow,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_normalize() -> None:
    assert _normalize("Hello, World!") == "hello world"


def test_kgram_hashes() -> None:
    hashes = _kgram_hashes("abcdefghijklmnopqrstuvwxyz", k=5)
    assert len(hashes) == 22  # 26 - 5 + 1


def test_kgram_hashes_deterministic_across_processes() -> None:
    """Regression: _kgram_hashes used to be built on the builtin hash(), which Python randomizes
    per process (PYTHONHASHSEED) unless disabled. Two processes with different seeds must still
    agree, or fingerprints computed before/after an app restart silently stop matching."""
    code = "from brainycat.fingerprints import _kgram_hashes; print(_kgram_hashes('the quick brown fox jumps', k=5))"
    out = {
        seed: subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
            cwd=str(Path(__file__).parents[2]),
            check=True,
        ).stdout
        for seed in ("1", "2")
    }
    assert out["1"] == out["2"]


def test_winnow_reduces() -> None:
    hashes = list(range(100))
    winnowed = _winnow(hashes, w=4)
    assert len(winnowed) < len(hashes)


def test_minhash_size() -> None:
    fp = list(range(50))
    mh = _minhash(fp, num_hashes=64)
    assert len(mh) == 64


def test_jaccard_minhash_identical() -> None:
    sig = list(range(64))
    assert _jaccard_minhash(sig, sig) == 1.0


def test_jaccard_minhash_different() -> None:
    a = list(range(64))
    b = list(range(64, 128))
    assert _jaccard_minhash(a, b) < 0.2


def test_structural_fingerprint() -> None:
    text = "Chapter 1\n" + "word " * 200 + "\nChapter 2\n" + "other " * 200
    result = _structural_fingerprint(text)
    assert result["chapter_count"] >= 1
    assert result["skeleton_hash"]


def test_cross_format_match_on_real_files() -> None:
    """The actual case this module exists for: the same book as an EPUB and as plain text (two
    different pipelines producing different whitespace/markup) must fingerprint as near-duplicates,
    and an unrelated text must not."""
    epub_text = _extract_full_text(str(FIXTURES / "pride_prejudice.epub"), "epub")
    txt_text = (FIXTURES / "pride_prejudice.txt").read_text(encoding="utf-8-sig")
    assert len(epub_text) > 10_000
    assert len(txt_text) > 10_000

    sig_a = _minhash(_text_fingerprint(epub_text))
    sig_b = _minhash(_text_fingerprint(txt_text))
    assert _jaccard_minhash(sig_a, sig_b) > 0.9  # same content, different extraction pipeline

    unrelated = " ".join(reversed(txt_text.split()))  # same vocabulary, not the same book: a real negative
    sig_c = _minhash(_text_fingerprint(unrelated))
    assert _jaccard_minhash(sig_a, sig_c) < 0.3


def test_minhash_stays_fast_on_a_huge_fingerprint() -> None:
    """Regression: _minhash used to run 128 unbounded passes over the whole input set with no size cap
    — measured 53s of synchronous CPU time on a real ~3.5M-character book's ~1.08M-element winnowed
    fingerprint (138M `hash((i, v))` calls), entirely blocking the single-process event loop for that
    whole duration. This is the likely real cause of the concurrent-load stalls seen throughout this
    project's test runs (see docs/ui-redesign/proposal.md, iterations 3-6, and fingerprints.py's
    _minhash docstring). A fingerprint this large must complete in a small fraction of a second now."""
    import time

    huge_fingerprint = list(range(1_100_000))
    start = time.monotonic()
    sig = _minhash(huge_fingerprint)
    elapsed = time.monotonic() - start
    assert len(sig) == 128
    assert elapsed < 5.0, f"took {elapsed:.1f}s — the size cap in _minhash regressed"


def test_minhash_downsampling_preserves_similarity_signal() -> None:
    """The downsampled minhash of a huge fingerprint must still correctly distinguish similar from
    dissimilar sets — capping the input for speed must not silently break what minhash is for."""
    a = list(range(1_100_000))
    b = list(range(1_100_000))  # identical
    c = list(range(2_000_000, 3_100_000))  # disjoint

    sig_a, sig_b, sig_c = _minhash(a), _minhash(b), _minhash(c)
    assert _jaccard_minhash(sig_a, sig_b) == 1.0
    assert _jaccard_minhash(sig_a, sig_c) < 0.1
