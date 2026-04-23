"""One-off script: fix dirty titles using Google Books canonical titles."""

import asyncio

import httpx


async def main() -> None:
    from brainycat.db import fetch_all, execute

    rows = await fetch_all("""
        SELECT id, isbn, title FROM books
        WHERE isbn IS NOT NULL AND length(isbn) >= 10
          AND (title LIKE '%,%' OR title LIKE '% - %' OR title LIKE '%(20%' OR title LIKE '%(19%')
        LIMIT 200
    """)
    print(f"Checking {len(rows)} books with messy titles + ISBNs...")
    fixed = 0
    async with httpx.AsyncClient(timeout=10) as client:
        for r in rows:
            isbn = r["isbn"]
            try:
                resp = await client.get(
                    f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}&maxResults=1"
                )
                if resp.status_code == 200:
                    items = resp.json().get("items", [])
                    if items:
                        vi = items[0]["volumeInfo"]
                        api_title = vi.get("title", "")
                        sub = vi.get("subtitle", "")
                        full = f"{api_title}: {sub}" if sub else api_title
                        if len(full) > 3 and full != r["title"]:
                            await execute("UPDATE books SET title = $1 WHERE id = $2", full, r["id"])
                            print(f"  ✅ {r['title'][:50]}")
                            print(f"     → {full[:50]}")
                            fixed += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"  ❌ {isbn}: {e}")
    print(f"\nFixed {fixed}/{len(rows)} titles")


if __name__ == "__main__":
    asyncio.run(main())
