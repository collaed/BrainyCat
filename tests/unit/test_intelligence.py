"""Tests for intelligence module."""
from brainycat.intelligence import _normalize, _jaccard

def test_normalize_basic() -> None:
    assert _normalize("Hello World!") == "hello world"

def test_normalize_comma_name() -> None:
    assert _normalize("Jordaine, Alex") == "alex jordaine"

def test_normalize_strips_punctuation() -> None:
    assert _normalize("O'Brien-Smith") == "o brien smith"

def test_jaccard_identical() -> None:
    assert _jaccard(["a", "b", "c"], ["a", "b", "c"]) == 1.0

def test_jaccard_disjoint() -> None:
    assert _jaccard(["a", "b"], ["c", "d"]) == 0.0

def test_jaccard_partial() -> None:
    assert _jaccard(["a", "b", "c"], ["b", "c", "d"]) == 0.5

def test_jaccard_empty() -> None:
    assert _jaccard([], ["a"]) == 0.0


def test_soundex_basic() -> None:
    from brainycat.intelligence import _soundex
    assert _soundex("Robert") == "R163"
    assert _soundex("Rupert") == "R163"  # Same soundex!

def test_soundex_tolkien() -> None:
    from brainycat.intelligence import _soundex
    assert _soundex("Tolkien") == _soundex("Tolkein")  # Misspelling matches

def test_soundex_empty() -> None:
    from brainycat.intelligence import _soundex
    assert _soundex("") == ""
