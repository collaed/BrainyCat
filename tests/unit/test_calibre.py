"""Tests for Calibre import with schema version handling."""

import os
import sqlite3
import tempfile

from brainycat.calibre_import import (
    _detect_schema,
    calibre_library_stats,
    detect_calibre_library,
    read_calibre_db,
)


def _create_calibre_db(path: str, version: int = 26) -> str:
    """Create a minimal Calibre metadata.db for testing."""
    db_path = os.path.join(path, "metadata.db")
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA user_version = {version}")

    # Core tables (all versions)
    conn.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT, sort TEXT, path TEXT, pubdate TEXT, timestamp TEXT, last_modified TEXT, series_index REAL DEFAULT 1, uuid TEXT, author_sort TEXT)")
    conn.execute("CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT, sort TEXT)")
    conn.execute("CREATE TABLE books_authors_link (id INTEGER PRIMARY KEY, book INTEGER, author INTEGER)")
    conn.execute("CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE books_tags_link (id INTEGER PRIMARY KEY, book INTEGER, tag INTEGER)")
    conn.execute("CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE books_series_link (id INTEGER PRIMARY KEY, book INTEGER, series INTEGER)")
    conn.execute("CREATE TABLE publishers (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE books_publishers_link (id INTEGER PRIMARY KEY, book INTEGER, publisher INTEGER)")
    conn.execute("CREATE TABLE languages (id INTEGER PRIMARY KEY, lang_code TEXT)")
    conn.execute("CREATE TABLE books_languages_link (id INTEGER PRIMARY KEY, book INTEGER, lang_code INTEGER)")
    conn.execute("CREATE TABLE data (id INTEGER PRIMARY KEY, book INTEGER, format TEXT, name TEXT, uncompressed_size INTEGER)")
    conn.execute("CREATE TABLE comments (id INTEGER PRIMARY KEY, book INTEGER, text TEXT)")
    conn.execute("CREATE TABLE ratings (id INTEGER PRIMARY KEY, rating INTEGER)")
    conn.execute("CREATE TABLE books_ratings_link (id INTEGER PRIMARY KEY, book INTEGER, rating INTEGER)")
    conn.execute("CREATE TABLE custom_columns (id INTEGER PRIMARY KEY, label TEXT, name TEXT, datatype TEXT)")

    # v18+ tables
    if version >= 18:
        conn.execute("CREATE TABLE identifiers (id INTEGER PRIMARY KEY, book INTEGER, type TEXT, val TEXT)")

    # v22+ tables
    if version >= 22:
        conn.execute("CREATE TABLE last_read_positions (id INTEGER PRIMARY KEY, book INTEGER, format TEXT, user TEXT, device TEXT, cfi TEXT, epoch REAL, pos_frac REAL)")

    # v23+ tables
    if version >= 23:
        conn.execute("CREATE TABLE annotations (id INTEGER PRIMARY KEY, book INTEGER, format TEXT, annotation_type TEXT, annotation_data TEXT)")

    # Insert test data
    conn.execute("INSERT INTO books (id, title, sort, path, series_index, uuid) VALUES (1, 'Test Book', 'Test Book', 'Author/Test Book (1)', 2.0, 'test-uuid-123')")
    conn.execute("INSERT INTO authors (id, name, sort) VALUES (1, 'Test Author', 'Author, Test')")
    conn.execute("INSERT INTO books_authors_link (book, author) VALUES (1, 1)")
    conn.execute("INSERT INTO tags (id, name) VALUES (1, 'fiction')")
    conn.execute("INSERT INTO books_tags_link (book, tag) VALUES (1, 1)")
    conn.execute("INSERT INTO series (id, name) VALUES (1, 'Test Series')")
    conn.execute("INSERT INTO books_series_link (book, series) VALUES (1, 1)")

    if version >= 18:
        conn.execute("INSERT INTO identifiers (book, type, val) VALUES (1, 'isbn', '9780123456789')")
        conn.execute("INSERT INTO identifiers (book, type, val) VALUES (1, 'asin', 'B00TEST1234')")

    conn.commit()
    conn.close()
    return path


def test_detect_nonexistent() -> None:
    assert detect_calibre_library("/nonexistent") is False


def test_detect_valid() -> None:
    with tempfile.TemporaryDirectory() as d:
        _create_calibre_db(d)
        assert detect_calibre_library(d) is True


def test_schema_detection_v26() -> None:
    with tempfile.TemporaryDirectory() as d:
        _create_calibre_db(d, version=26)
        conn = sqlite3.connect(os.path.join(d, "metadata.db"))
        schema = _detect_schema(conn)
        conn.close()
        assert schema["version"] == 26
        assert schema["has_identifiers"] is True
        assert schema["has_annotations"] is True
        assert schema["has_series_index"] is True
        assert schema["has_uuid"] is True


def test_schema_detection_v17() -> None:
    with tempfile.TemporaryDirectory() as d:
        _create_calibre_db(d, version=17)
        conn = sqlite3.connect(os.path.join(d, "metadata.db"))
        schema = _detect_schema(conn)
        conn.close()
        assert schema["version"] == 17
        assert schema["has_identifiers"] is False
        assert schema["has_annotations"] is False


def test_read_v26_gets_isbn_from_identifiers() -> None:
    with tempfile.TemporaryDirectory() as d:
        _create_calibre_db(d, version=26)
        books = read_calibre_db(d)
        assert len(books) == 1
        assert books[0]["isbn"] == "9780123456789"
        assert books[0]["identifiers"]["asin"] == "B00TEST1234"


def test_read_series_index_correct() -> None:
    with tempfile.TemporaryDirectory() as d:
        _create_calibre_db(d, version=26)
        books = read_calibre_db(d)
        assert books[0]["series_name"] == "Test Series"
        assert books[0]["series_index"] == 2.0  # NOT the book ID


def test_read_authors() -> None:
    with tempfile.TemporaryDirectory() as d:
        _create_calibre_db(d, version=26)
        books = read_calibre_db(d)
        assert books[0]["authors"][0]["name"] == "Test Author"
        assert books[0]["authors"][0]["sort"] == "Author, Test"


def test_read_tags() -> None:
    with tempfile.TemporaryDirectory() as d:
        _create_calibre_db(d, version=26)
        books = read_calibre_db(d)
        assert "fiction" in books[0]["tags"]


def test_stats() -> None:
    with tempfile.TemporaryDirectory() as d:
        _create_calibre_db(d, version=26)
        stats = calibre_library_stats(d)
        assert stats["books"] == 1
        assert stats["authors"] == 1
        assert stats["schema"]["version"] == 26
        assert "isbn" in stats.get("identifier_types", [])


def test_v17_no_identifiers() -> None:
    """Pre-v18 libraries have no identifiers table."""
    with tempfile.TemporaryDirectory() as d:
        _create_calibre_db(d, version=17)
        books = read_calibre_db(d)
        assert len(books) == 1
        assert books[0]["isbn"] is None  # No identifiers table, no books.isbn col in our test
        assert books[0]["identifiers"] == {}
