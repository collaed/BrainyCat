"""Unified text profiling pipeline — single-pass extraction for incipit, fingerprint, and embedding.

Reads each book file once and computes all text-derived signatures in one pass:
1. Incipit (first meaningful sentence)
2. Characteristic words (longest, most specific)
3. Winnowed fingerprint + MinHash (for dedup)
4. TF-IDF embedding vector (for similarity)

Designed for the J5005's constraints: streams text in chunks, yields between books.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import UUID

from brainycat import db
from brainycat.db import execute, fetch_all, fetch_one

# Checkpoint: track last processed book to enable resumption
CHECKPOINT_KEY = "text_profiler_last_id"


async def _get_checkpoint() -> str | None:
    row = await fetch_one(
        "SELECT value FROM kv_store WHERE key = $1", CHECKPOINT_KEY
    )
    return row["value"] if row else None


async def _set_checkpoint(book_id: str) -> None:
    await execute(
        "INSERT INTO kv_store (key, value) VALUES ($1, $2) "
        "ON CONFLICT (key) DO UPDATE SET value = $2",
        CHECKPOINT_KEY, str(book_id),
    )


async def get_backlog_count() -> int:
    row = await fetch_one("""
        SELECT count(*) as n FROM books b
        JOIN book_files bf ON bf.book_id = b.id
        LEFT JOIN book_fingerprints fp ON fp.book_id = b.id
        WHERE fp.book_id IS NULL AND bf.format IN ('epub','pdf')
    """)
    return row["n"] if row else 0


async def process_batch(batch_size: int = 5) -> dict[str, Any]:
    """Process a batch of books: extract text once, compute all signatures."""
    from brainycat.embeddings import generate_embedding
    from brainycat.fingerprints import (
        _edition_info,
        _extract_full_text,
        _minhash,
        _structural_fingerprint,
        _text_fingerprint,
    )
    from brainycat.incipit import extract_characteristics

    checkpoint = await _get_checkpoint()

    # Fetch books needing processing (no fingerprint yet = not processed)
    query = """
        SELECT b.id, b.title, bf.file_path, bf.format
        FROM books b
        JOIN book_files bf ON bf.book_id = b.id
        LEFT JOIN book_fingerprints fp ON fp.book_id = b.id
        WHERE fp.book_id IS NULL AND bf.format IN ('epub','pdf')
    """
    params: list[Any] = []
    if checkpoint:
        query += " AND b.id > $1"
        params.append(UUID(checkpoint))
    query += " ORDER BY b.id LIMIT $" + str(len(params) + 1)
    params.append(batch_size)

    rows = await fetch_all(query, *params)
    if not rows:
        # Reset checkpoint — we've completed a full pass
        await _set_checkpoint("")
        return {"processed": 0, "status": "complete"}

    processed = 0
    for row in rows:
        book_id = row["id"]
        file_path = row["file_path"]
        fmt = row["format"]

        if not os.path.isfile(file_path):
            await _set_checkpoint(str(book_id))
            continue

        # Single file read — extract full text
        text = _extract_full_text(file_path, fmt)
        if len(text) < 500:
            await _set_checkpoint(str(book_id))
            continue

        # 1. Incipit + characteristic words
        chars = extract_characteristics(text)

        # 2. Fingerprint (winnowing + minhash + structure)
        struct = _structural_fingerprint(text)
        winnowed = _text_fingerprint(text)
        minhash = _minhash(winnowed)
        edition = _edition_info(text)

        # Store fingerprint
        await execute(
            """INSERT INTO book_fingerprints (book_id, samples, sample_count, total_chars, computed_at)
               VALUES ($1, $2, $3, $4, now())
               ON CONFLICT (book_id) DO UPDATE SET samples=$2, sample_count=$3, total_chars=$4, computed_at=now()""",
            book_id,
            [
                struct["skeleton_hash"],
                json.dumps(minhash[:64]),
                json.dumps(struct["anchors"][:20]),
                json.dumps(edition),
            ],
            len(minhash),
            len(text),
        )

        # 3. Embedding (if not already computed)
        existing_emb = await fetch_one("SELECT embedding FROM books WHERE id = $1", book_id)
        if existing_emb and existing_emb["embedding"] is None:
            title = row["title"] or ""
            # Build embedding text from title + first 500 chars of body
            emb_text = f"{title} {text[:500]}"
            vec = await generate_embedding(emb_text)
            if vec:
                vec_str = "[" + ",".join(str(v) for v in vec) + "]"
                await execute("UPDATE books SET embedding = $1::vector WHERE id = $2", vec_str, book_id)

        # 4. Store text profiles in extra_metadata
        meta_update = {k: v for k, v in chars.items() if v}
        if edition:
            meta_update["edition_info"] = edition
        if meta_update:
            await execute(
                "UPDATE books SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || $1::jsonb, updated_at = now() WHERE id = $2",
                json.dumps(meta_update),
                book_id,
            )

        await _set_checkpoint(str(book_id))
        processed += 1
        await asyncio.sleep(0)  # yield to event loop

    return {"processed": processed, "batch_size": batch_size}
