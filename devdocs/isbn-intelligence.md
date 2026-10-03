# ISBN Intelligence

## Why ISBN Matters

ISBN is the primary key for enrichment. With an ISBN, local SQLite lookup has 68% hit rate. Without it, you're stuck with fuzzy title matching (~28% accuracy).

**Current coverage:** 27,354 of 63,504 books have ISBN (43%). The remaining 36,150 need ISBN extraction.

## 6 Extraction Methods

| Method | File | How | When used |
|--------|------|-----|-----------|
| 1. OPF metadata | `isbn.py` | Parse EPUB/MOBI internal OPF XML, look for `<dc:identifier>` | On upload |
| 2. Full-text scan | `isbn.py` | Regex for ISBN-10/13 patterns in first 5000 chars | On upload |
| 3. Barcode decode | `isbn.py` (pyzbar) | Decode EAN-13 barcodes from cover/copyright page images | On OCR |
| 4. Filename parsing | `isbn.py` | Extract 10/13-digit sequences from filename | On upload |
| 5. Title matching | `fast_local.py` | Fuzzy match title against OL dump → get ISBN from match | Background loop |
| 6. OCR copyright page | `ocr_copyright.py` | OCR first 5 pages, regex for ISBN patterns | Background loop (broken) |

### Extraction Priority

Methods 1-4 run at ingest time. Methods 5-6 run in background loops for books that still lack ISBN.

## ISBN Validation

```python
def is_valid_isbn13(isbn: str) -> bool:
    """Check-digit validation (modulo 10 with alternating 1/3 weights)."""
    digits = [int(d) for d in isbn if d.isdigit()]
    if len(digits) != 13:
        return False
    check = sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:12])) % 10
    return (10 - check) % 10 == digits[12]
```

Also validates ISBN-10 (modulo 11) and converts between formats.

## Unicode Dash Handling

Real-world ISBNs use various dash characters:
- `978-1-118-99094-0` (ASCII hyphen)
- `978‐1‐118‐99094‐0` (U+2010 HYPHEN)
- `978–1–118–99094–0` (U+2013 EN DASH)
- `978―1―118―99094―0` (U+2015 HORIZONTAL BAR)

All are stripped before validation. The `isbn.py` module handles this via:
```python
DASH_CHARS = "-\u2010\u2011\u2012\u2013\u2014\u2015"
isbn = isbn.translate(str.maketrans("", "", DASH_CHARS + " "))
```

## 285 Registration Groups

The ISBN Range Message (official RangeMessage.xml) defines which country/language each ISBN prefix belongs to:

| Prefix | Region | Used for |
|--------|--------|----------|
| 978-0, 978-1 | English-speaking | Route to LoC, WorldCat, British Library |
| 978-2 | French-speaking | Route to BnF |
| 978-3 | German-speaking | Route to DNB |
| 978-4 | Japan | Route to NDL, Rakuten |
| 978-5 | Russia/CIS | — |
| 978-7 | China | Route to Douban |
| 978-84 | Spain | Route to BNE |
| 979-10 | France (new prefix) | Route to BnF |

This is used by `isbn_ranges.py` to determine which regional library to query first for a given book.

## Multi-ISBN Storage

A single book can have multiple ISBNs:
- Print ISBN-13
- eBook ISBN-13
- PDF ISBN
- Audiobook ISBN
- Old ISBN-10

All are stored. The `isbn` column on `books` holds the primary one (usually the first valid ISBN-13 found). Additional ISBNs go into `extra_metadata.edition_info.isbns` or the `book_links` table.

## Check-Digit Completion

For ISBNs found with 12 digits (missing check digit), the validator computes and appends it:
```python
def complete_isbn13(partial: str) -> str:
    """Given 12 digits, compute and append the check digit."""
    digits = [int(d) for d in partial if d.isdigit()]
    check = (10 - sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits)) % 10) % 10
    return partial + str(check)
```

## Current State

- 27,354 books have ISBN (43%)
- 36,150 books have no ISBN
- Of books with ISBN: 27,351 already locally enriched (99.99% — pool nearly exhausted)
- Books without ISBN need: title matching (14/50 = 28% hit rate) or OCR (broken due to statement_timeout)
