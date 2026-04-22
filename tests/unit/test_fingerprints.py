"""Tests for fingerprinting."""
from brainycat.fingerprints import _normalize, _kgram_hashes, _winnow, _minhash, _jaccard_minhash, _structural_fingerprint

def test_normalize() -> None:
    assert _normalize("Hello, World!") == "hello world"

def test_kgram_hashes() -> None:
    hashes = _kgram_hashes("abcdefghijklmnopqrstuvwxyz", k=5)
    assert len(hashes) == 22  # 26 - 5 + 1

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
