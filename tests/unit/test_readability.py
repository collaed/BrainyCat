"""Tests for readability scoring."""

from brainycat.readability import _count_syllables, compute_readability


def test_count_syllables() -> None:
    assert _count_syllables("cat") == 1
    assert _count_syllables("hello") == 2
    assert _count_syllables("beautiful") == 3
    assert _count_syllables("extraordinary") == 5


def test_readability_easy_text() -> None:
    text = "The cat sat on the mat. The dog ran in the park. It was a nice day. " * 10
    r = compute_readability(text)
    assert r["level"] in ("easy", "standard")
    assert r["flesch_ease"] > 60


def test_readability_hard_text() -> None:
    text = ("The epistemological ramifications of phenomenological hermeneutics "
            "necessitate a comprehensive reevaluation of ontological presuppositions. " * 10)
    r = compute_readability(text)
    assert r["level"] in ("difficult", "very_difficult", "moderate")
    assert r["fk_grade"] > 10


def test_readability_too_short() -> None:
    r = compute_readability("Hi.")
    assert "error" in r
