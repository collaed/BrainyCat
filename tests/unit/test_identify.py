from __future__ import annotations

from brainycat.identify import (
    Candidate,
    Decision,
    Record,
    apply_verification,
    authors_overlap,
    decide,
    filename_isbn,
    reject_shared,
    resolve,
    same_title,
    to_isbn13,
    verify,
)

GOOD13 = "9780306406157"


def test_to_isbn13_valid_and_converted() -> None:
    assert to_isbn13("978-0-306-40615-7") == GOOD13
    assert to_isbn13("0306406152") == GOOD13


def test_to_isbn13_never_invents_check_digit() -> None:
    assert to_isbn13("978030640615") is None  # 12 digits
    assert to_isbn13("9780306406158") is None  # bad checksum


def test_filename_isbn_is_token_bounded() -> None:
    assert filename_isbn(f"Title -- Author -- {GOOD13} -- hash.epub") == GOOD13
    assert filename_isbn(f"Title [{GOOD13}].epub") == GOOD13
    assert filename_isbn(f"deadbeef{GOOD13}cafe.epub") is None  # inside a hash
    assert filename_isbn(f"1{GOOD13}.epub") is None  # inside a longer number


def test_resolve_grades_by_agreement() -> None:
    assert resolve({"opf": GOOD13, "text": "0306406152"}).confidence == "certain"  # type: ignore[union-attr]
    assert resolve({"opf": GOOD13}).confidence == "probable"  # type: ignore[union-attr]
    assert resolve({"text": GOOD13}).confidence == "possible"  # type: ignore[union-attr]
    contested = resolve({"opf": GOOD13, "text": "9781849684033"})
    assert contested is not None
    assert contested.confidence == "possible"
    assert contested.alternates
    assert resolve({"opf": "1234567890"}) is None


def test_resolve_majority_beats_priority() -> None:
    c = resolve({"opf": "9781849684033", "filename": GOOD13, "text": GOOD13})
    assert c is not None
    assert (c.isbn, c.confidence) == (GOOD13, "probable")


def test_same_title() -> None:
    assert same_title("ESXi Cookbook", "esxi cookbook")
    assert not same_title("La trame", "ESXi Cookbook")
    assert not same_title("Beta", "Delta")
    assert same_title("Thérapie", "Therapie")
    assert same_title("Rock &amp; Roll", "Rock & Roll")


def test_reject_shared_drops_placeholder_and_keeps_majority() -> None:
    cands = {f"f{i}": Candidate(GOOD13, "filename", "probable") for i in range(4)}
    titles = {"f0": "Alpha", "f1": "Beta", "f2": "Gamma", "f3": "Delta"}
    assert len(reject_shared(cands, titles)) == 4  # placeholder: no majority
    cands = {k: Candidate(GOOD13, "opf", "probable") for k in ("a", "b", "c")}
    titles = {"a": "ESXi Cookbook", "b": "ESXi Cookbook", "c": "La trame"}
    assert reject_shared(cands, titles) == ["c"]
    assert cands["a"].confidence == "probable"


def test_authors_overlap_handles_formats_and_accents() -> None:
    assert authors_overlap(["Jane Austen"], ["Austen, Jane"])
    assert authors_overlap(["Éric Zola"], ["Eric Zola"])
    assert not authors_overlap(["Jane Austen"], ["Emile Zola"])


def test_verify_verdicts() -> None:
    rec = Record("Pride and Prejudice", ["Jane Austen"])
    assert verify("Pride and Prejudice", [], rec) == "verified"
    assert verify("Orgueil et Préjugés", ["Austen, Jane"], rec) == "verified"  # translated title, same author
    assert verify("Le dahlia noir", ["James Ellroy"], rec) == "mismatch"
    assert verify("Anything", [], None) == "unknown"
    assert verify("", [], rec) == "unknown"


def test_apply_verification() -> None:
    c = Candidate(GOOD13, "opf", "probable")
    apply_verification(c, "mismatch")
    assert c.confidence == "possible"
    apply_verification(c, "verified")
    assert c.confidence == "certain"


def test_decide_writes_on_agreement_without_expensive_scan() -> None:
    d = decide({"opf": GOOD13, "filename": GOOD13})
    assert d.write
    assert (d.isbn, d.confidence) == (GOOD13, "certain")


def test_decide_writes_single_strong_source_without_expensive_scan() -> None:
    d = decide({"opf": GOOD13})
    assert d.write
    assert d.confidence == "probable"


def test_decide_falls_back_to_expensive_evidence_when_cheap_is_contested() -> None:
    cheap = {"opf": GOOD13, "filename": "9781849684033"}  # single-voice-each: possible
    assert decide(cheap).confidence == "possible"
    d = decide(cheap, expensive={"text": GOOD13})  # third source breaks the tie
    assert d.write
    assert d.isbn == GOOD13


def test_decide_queues_when_nothing_resolves_to_auto_apply() -> None:
    d = decide({}, expensive={"text": GOOD13})
    assert not d.write
    assert d.confidence == "possible"
    assert d.isbn == GOOD13


def test_decide_no_evidence_at_all() -> None:
    d = decide({})
    assert d == Decision(None, None, None, write=False)
