"""MARC21 record export/import — interop with real library systems."""

from __future__ import annotations

from typing import Any

from brainycat import db


def book_to_marc(book: dict[str, Any], author: str = "") -> bytes:
    """Convert a book record to MARC21 binary format."""
    # MARC21 structure: Leader + Directory + Fields
    fields: list[tuple[str, str]] = []

    # 001 - Control Number
    fields.append(("001", str(book.get("id", ""))))
    # 020 - ISBN
    if book.get("isbn"):
        fields.append(("020", f"\x1fa{book['isbn']}"))
    # 100 - Author
    if author:
        fields.append(("100", f"\x1fa{author}"))
    # 245 - Title
    if book.get("title"):
        fields.append(("245", f"\x1fa{book['title']}"))
    # 260 - Publisher/Date
    if book.get("pubdate"):
        fields.append(("260", f"\x1fc{book['pubdate']}"))
    # 300 - Pages
    if book.get("page_count"):
        fields.append(("300", f"\x1fa{book['page_count']} p."))
    # 520 - Description
    if book.get("description"):
        fields.append(("520", f"\x1fa{book['description'][:500]}"))
    # 041 - Language
    if book.get("language"):
        fields.append(("041", f"\x1fa{book['language']}"))

    # Build MARC record
    directory = b""
    data = b""
    for tag, value in fields:
        field_data = value.encode("utf-8") + b"\x1e"
        directory += tag.encode("ascii") + f"{len(field_data):04d}".encode() + f"{len(data):05d}".encode()
        data += field_data

    directory += b"\x1e"
    base_address = 24 + len(directory)
    record_length = base_address + len(data) + 1

    leader = f"{record_length:05d}nam  22{base_address:05d}   4500".encode("ascii")
    return leader + directory + data + b"\x1d"


async def export_marc(limit: int = 100) -> bytes:
    """Export library as MARC21 file (multiple records)."""
    books = await db.fetch_all(
        """SELECT b.id, b.title, b.isbn, b.description, b.language, b.pubdate, b.page_count,
                  a.name as author
           FROM books b
           LEFT JOIN books_authors ba ON ba.book_id = b.id
           LEFT JOIN authors a ON a.id = ba.author_id
           WHERE b.quality_score >= 50
           ORDER BY b.title LIMIT $1""",
        limit,
    )
    records = b""
    for book in books:
        records += book_to_marc(dict(book), book.get("author") or "")
    return records


def parse_marc_record(data: bytes) -> dict[str, Any]:
    """Parse a single MARC21 record into a dict."""
    if len(data) < 25:
        return {}
    record_length = int(data[:5])
    base_address = int(data[12:17])
    directory = data[24 : base_address - 1]
    field_data = data[base_address:]

    result: dict[str, Any] = {}
    for i in range(0, len(directory), 12):
        tag = directory[i : i + 3].decode("ascii")
        length = int(directory[i + 3 : i + 7])
        start = int(directory[i + 7 : i + 12])
        value = field_data[start : start + length - 1].decode("utf-8", errors="replace")
        # Strip subfield indicators
        value = value.replace("\x1fa", "").replace("\x1fc", "").strip()

        if tag == "020":
            result["isbn"] = value
        elif tag == "100":
            result["author"] = value
        elif tag == "245":
            result["title"] = value
        elif tag == "260":
            result["pubdate"] = value
        elif tag == "520":
            result["description"] = value
        elif tag == "041":
            result["language"] = value

    return result
