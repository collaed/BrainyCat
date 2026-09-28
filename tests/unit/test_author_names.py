"""Tests for compound author-string splitting."""

from brainycat.author_names import split_authors


def test_single_plain_name_unchanged() -> None:
    assert split_authors("Marie Kondo") == ["Marie Kondo"]


def test_last_first_reordered() -> None:
    assert split_authors("Lamarche,Caroline") == ["Caroline Lamarche"]
    assert split_authors("Kondo,Marie") == ["Marie Kondo"]


def test_multiple_full_names_comma_separated() -> None:
    assert split_authors("Konrad Banachewicz,Luca Massaron,Anthony Goldbloom") == [
        "Konrad Banachewicz",
        "Luca Massaron",
        "Anthony Goldbloom",
    ]


def test_ampersand_separated() -> None:
    assert split_authors("Gene Kim & Kevin Behr & George Spafford") == [
        "Gene Kim",
        "Kevin Behr",
        "George Spafford",
    ]


def test_and_separated() -> None:
    assert split_authors("Dawn Griffiths and David Griffiths") == ["Dawn Griffiths", "David Griffiths"]


def test_et_separated() -> None:
    assert split_authors("Ed Tittel et Jeff Noble") == ["Ed Tittel", "Jeff Noble"]


def test_semicolon_separated_last_first_pairs() -> None:
    assert split_authors("Sutz, Richard.; Weverka, Peter.") == ["Richard Sutz", "Peter Weverka"]


def test_chained_last_first_pairs_by_comma() -> None:
    assert split_authors("Christensen, Paulina.,Fox, Anne.,Foster, Wendy.") == [
        "Paulina Christensen",
        "Anne Fox",
        "Wendy Foster",
    ]


def test_trailing_birth_year_stripped() -> None:
    assert split_authors("Foster, Wendy, 19..-") == ["Wendy Foster"]
    assert split_authors("Reseck, John, 1935-") == ["John Reseck"]


def test_oxford_comma_list() -> None:
    assert split_authors("Betsy Beyer, Chris Jones, Jennifer Petoff, and Niall Richard Murphy") == [
        "Betsy Beyer",
        "Chris Jones",
        "Jennifer Petoff",
        "Niall Richard Murphy",
    ]


def test_empty_and_none() -> None:
    assert split_authors("") == []
    assert split_authors(None) == []
    assert split_authors("   ") == []


def test_deduplicates_case_insensitively() -> None:
    assert split_authors("Jane Doe & jane doe") == ["Jane Doe"]


def test_multiword_surname_last_first() -> None:
    assert split_authors("de la Cruz, Valeria") == ["Valeria de la Cruz"]


def test_two_full_names_comma_separated() -> None:
    assert split_authors("Ivan Ward, Oscar Zarate") == ["Ivan Ward", "Oscar Zarate"]


def test_bracketed_restatement_stripped() -> None:
    assert split_authors("Martha Alderson [Alderson, Martha]") == ["Martha Alderson"]
    assert split_authors("Moore, Ashley [Moore, Ashley]") == ["Ashley Moore"]


def test_role_word_not_treated_as_author() -> None:
    assert split_authors("Silen, Andrea, author") == ["Andrea Silen"]
    assert split_authors("Manara, Milo, author, illustrator") == ["Milo Manara"]


def test_professional_suffix_not_reordered_as_firstname() -> None:
    assert split_authors("Laura L. Smith, PhD") == ["Laura L. Smith"]
    assert split_authors("Harville Hendrix, Ph.D.") == ["Harville Hendrix"]


def test_chained_pairs_with_multiword_firstname() -> None:
    assert split_authors("Mairowitz, David Zane,Appignanesi, Richard.,Crumb, R.") == [
        "David Zane Mairowitz",
        "Richard Appignanesi",
        "R Crumb",
    ]
