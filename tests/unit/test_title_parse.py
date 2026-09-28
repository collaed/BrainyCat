"""Tests for title_parse.py, using real messy titles from the library."""

from brainycat.title_parse import parse_title


def test_anna_archive_full_structure() -> None:
    r = parse_title(
        "21b50b4d Autism Your Questions Answered -- Romeo Vitelli -- 1, 2024 -- "
        "Bloomsbury Publishing USA -- 9781440881565 -- 1e9c3d90f7395ba6b878c4b76e431e7a -- Anna’s Archive"
    )
    assert r.title == "Autism Your Questions Answered"
    assert r.author == "Romeo Vitelli"
    assert r.isbn == "9781440881565"
    assert r.publisher == "Bloomsbury Publishing USA"
    assert r.year == "2024"
    assert r.confidence == "high"


def test_anna_archive_with_place_no_year_field() -> None:
    r = parse_title(
        "5a096344 L'essentiel du japonais en 2 minutes, c'est malin -- Nao Sensei -- France, France -- "
        "Éditions Leduc -- 9791028512958 -- 93e3c6798f82c1df04b31b13fae7c06d -- Anna’s Archive"
    )
    assert r.title == "L'essentiel du japonais en 2 minutes, c'est malin"
    assert r.author == "Nao Sensei"
    assert r.isbn == "9791028512958"
    assert r.publisher == "Éditions Leduc"


def test_anna_archive_minimal_no_extra_metadata() -> None:
    r = parse_title("c1889e12 Goddess -- K D West,K D West -- 2d3857477610acb4828a9e1828fabc27 -- Anna’s Archive")
    assert r.title == "Goddess"
    assert r.author == "K D West,K D West"
    assert r.isbn is None


def test_anna_archive_french_no_year() -> None:
    r = parse_title(
        "b2b131cc La philosophie en 50 citations clés pour les Nuls -- Godin, Christian -- 2019 -- "
        "First (Éditions) -- c278cda87a337ac2e637570b2a8338c5 -- Anna’s Archive"
    )
    assert r.title == "La philosophie en 50 citations clés pour les Nuls"
    assert r.author == "Godin, Christian"
    assert r.publisher == "First (Éditions)"
    assert r.year == "2019"


def test_libgen_with_series_bracket() -> None:
    r = parse_title(
        "53c2b510 [O'Reilly's Head first series] Beighley, Lynn Morrison, Michael - "
        "Head First Php And Mysql (2009, O'Reilly Media) - libgen.li"
    )
    assert r.title == "Head First Php And Mysql"
    assert r.author == "Beighley, Lynn Morrison, Michael"
    assert r.publisher == "O'Reilly Media"
    assert r.year == "2009"


def test_libgen_no_series() -> None:
    r = parse_title("20da7613 Héctor García, Francesc Miralles - La méthode Ikigai (2018, Solar) - libgen.li")
    assert r.title == "La méthode Ikigai"
    assert r.author == "Héctor García, Francesc Miralles"
    assert r.publisher == "Solar"
    assert r.year == "2018"


def test_leading_bare_isbn_and_leaked_extension() -> None:
    r = parse_title("9782849336212 Burn-after-writing BAT.indd")
    assert r.isbn == "9782849336212"
    assert r.title == "Burn-after-writing"


def test_plain_hex_prefix_only() -> None:
    r = parse_title("b5179139 Domain Driven Design - Tackling Complexity in the Heart of Software")
    assert r.title == "Domain Driven Design - Tackling Complexity in the Heart of Software"
    assert r.confidence == "low"


def test_plain_hex_prefix_with_plus() -> None:
    r = parse_title("7f3a0d30 AI Agents 75+ Use Cases Transforming Enterprises")
    assert r.title == "AI Agents 75+ Use Cases Transforming Enterprises"


def test_single_slash_in_real_title_not_mangled() -> None:
    # Real titles with one "/" must not be treated as a folder-path leak.
    for title in [
        "My Memoir Into Submission: An Erotic Dominant / Submissive Romance",
        "SDI/TDI Divemaster Manual",
        "La science-fiction soviétique / anthologie",
        "Modèle epub 15/12/2013",
    ]:
        r = parse_title(title)
        assert r.title == title
        assert r.confidence == "low"


def test_three_segment_slash_leak_with_repeated_author() -> None:
    r = parse_title(
        "Erotique/James,E. L./Fifty Shades/Fifty Shades - 03 - Cinquante nuances plus claires - James,E. L."
    )
    assert r.title == "Fifty Shades - 03 - Cinquante nuances plus claires"
    assert r.author == "James,E. L."


def test_folder_path_leak_with_duplicate_author() -> None:
    r = parse_title("Philosophie/Onfray,Michel//Antimanuel De Philosophie - Onfray,Michel")
    assert r.title == "Antimanuel De Philosophie"
    assert r.author == "Onfray,Michel"


def test_truncated_title_left_as_is() -> None:
    r = parse_title("The Glycemic Index Diet for Dum")
    assert r.title == "The Glycemic Index Diet for Dum"
    assert r.confidence == "low"
