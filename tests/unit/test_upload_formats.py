"""Regression test: the upload format allowlist must not silently reject zips or azw3.

A zip batch upload used to be rejected outright (".zip" wasn't in ALLOWED_FORMATS, so the
extraction code below it was dead), and .azw3 (a common Kindle format) was rejected the same way
despite the rest of the app (extract.py, format_convert.py) already supporting it.
"""

from brainycat.books import ALLOWED_FORMATS, ZIP_FORMATS


def test_azw3_is_an_allowed_single_file_format() -> None:
    assert ".azw3" in ALLOWED_FORMATS


def test_zip_is_only_allowed_as_a_batch_container() -> None:
    assert ".zip" not in ALLOWED_FORMATS
    assert ".zip" in ZIP_FORMATS


def test_zip_formats_is_a_superset_of_allowed_formats() -> None:
    assert ALLOWED_FORMATS < ZIP_FORMATS
