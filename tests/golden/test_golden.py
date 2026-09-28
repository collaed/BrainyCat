"""Golden-set gate. Today: no auto-identification may contradict the manifest (precision guard).
Coverage thresholds from spec R15 are enforced once the ladder (T6) exists."""

from __future__ import annotations

from tests.golden.runner import HERE, run, score


def test_no_wrong_identifications() -> None:
    r = run(HERE / "manifest.yaml")
    assert r["rows"], "golden manifest resolved no files"
    wrong = [(x["file"], x["why"]) for x in r["rows"] if x["outcome"] == "wrong"]
    assert not wrong, wrong


def test_score_flags_fabricated_isbn() -> None:
    assert score({"isbn13": None}, {"isbn": "9780306406157"})[0] == "wrong"
    assert score({"isbn13": "9780306406157"}, {"isbn": "0306406152"})[0] == "correct"
    assert score({"title": "A"}, {})[0] == "none"


def test_unlabeled_entries_are_not_scored() -> None:
    assert score({}, {"isbn": "9780306406157"})[0] == "unlabeled"
