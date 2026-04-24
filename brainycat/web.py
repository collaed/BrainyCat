"""FastAPI application — all routes for BrainyCat."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from brainycat import (
    auth,
    books,
    db,
)
from brainycat.auth import get_current_user
from brainycat.http_client import get_client
from brainycat.logging import setup_logging

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    await db.get_pool()
    await auth.seed_users()
    from brainycat.scheduler import start_scheduler

    await start_scheduler()
    yield
    await db.close_pool()


app = FastAPI(title="BrainyCat", version="0.1.0", lifespan=lifespan)


@app.get("/")
async def root() -> RedirectResponse:
    """Redirect to setup if no users, otherwise to library."""
    count = await db.fetch_one("SELECT count(*) as c FROM users")
    if count["c"] == 0:
        return RedirectResponse(url="./static/setup.html")
    return RedirectResponse(url="./static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup() -> None:

    get_client()  # Initialize shared client
    from brainycat.rate_limit import seed_from_db

    await seed_from_db()  # Pre-set backoffs from recent failure history


@app.on_event("shutdown")
async def shutdown() -> None:
    from brainycat.http_client import close_client
    from brainycat.log import info

    info("Shutting down BrainyCat...")
    await close_client()
    info("Shutdown complete")


# ABS mobile app compatibility
from brainycat.abs_compat import router as abs_router  # noqa: E402
from brainycat.routes.admin import router as admin_router  # noqa: E402
from brainycat.routes.ai import router as ai_router  # noqa: E402
from brainycat.routes.auth import router as auth_router  # noqa: E402
from brainycat.routes.books import router as books_router  # noqa: E402
from brainycat.routes.catalog import router as catalog_router  # noqa: E402
from brainycat.routes.enrichment import router as enrichment_router  # noqa: E402
from brainycat.routes.media import router as media_router  # noqa: E402
from brainycat.routes.reader import router as reader_router  # noqa: E402
from brainycat.routes.social import router as social_router  # noqa: E402

app.include_router(abs_router)
app.include_router(catalog_router)
app.include_router(books_router)
app.include_router(enrichment_router)
app.include_router(media_router)
app.include_router(social_router)
app.include_router(reader_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(ai_router)


# ── Health ────────────────────────────────────────────────────────────────
@app.get("/api/v1/health")
async def health() -> dict[str, Any]:
    s = await db.health_check()
    return {"status": "ok" if s.get("connected") else "degraded", "db": s}


# ── Auth ──────────────────────────────────────────────────────────────────
app.post("/api/v1/login")(auth.login)
app.post("/api/v1/logout")(auth.logout)
app.get("/api/v1/me")(auth.me)
app.get("/api/v1/users")(auth.list_users)
app.patch("/api/v1/users/{user_id}")(auth.update_user)
app.patch("/api/v1/me/preferences")(auth.update_preferences)

# ── Books CRUD ────────────────────────────────────────────────────────────
app.post("/api/v1/books/upload")(books.upload_book)
app.get("/api/v1/books")(books.list_books)
app.get("/api/v1/books/{book_id}")(books.get_book)
app.patch("/api/v1/books/{book_id}")(books.update_book)
app.delete("/api/v1/books/{book_id}")(books.delete_book)
app.get("/api/v1/books/{book_id}/cover")(books.serve_cover)
app.get("/api/v1/books/{book_id}/file/{file_id}")(books.serve_file)


# ── Author update
class AuthorUpdate(BaseModel):
    author: str


class CreateSeriesBody(BaseModel):
    series_name: str
    book_ids: list[str]


class MergeAuthorsBody(BaseModel):
    keep_id: str
    merge_id: str


class LinkDuplicateBody(BaseModel):
    book_a_id: str
    book_b_id: str
    link_type: str = "edition"


class BatchActionsBody(BaseModel):
    actions: list[dict[str, Any]]


class ProgressUpdate(BaseModel):
    position: str | None = None
    position_timestamp: float | None = None
    percentage: float = 0
    is_finished: bool = False


class BookmarkCreate(BaseModel):
    position: str
    title: str | None = None


class AnnotationCreate(BaseModel):
    cfi_range: str
    text_content: str | None = None
    note: str | None = None
    color: str = "#ffeb3b"


class NoteBody(BaseModel):
    content: str


def _extract_paragraphs(epub_path: str) -> list[str]:
    """Extract all paragraphs from an EPUB."""
    try:
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(epub_path, options={"ignore_ncx": True})
        paragraphs = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            for p in soup.find_all("p"):
                text = p.get_text(strip=True)
                if text and len(text) > 5:
                    paragraphs.append(text)
        return paragraphs
    except Exception:
        return []


class BulkTagBody(BaseModel):
    book_ids: list[str]
    tag: str
    action: str = "add"  # add or remove


class BulkEnrichBody(BaseModel):
    book_ids: list[str]


class BatchTagBody(BaseModel):
    book_ids: list[str]
    tags: list[str]


class BatchEnrichBody(BaseModel):
    book_ids: list[str]


class BatchDeleteBody(BaseModel):
    book_ids: list[str]


class MergeBody(BaseModel):
    book_ids: list[str]
    title: str
    author: str = ""


@app.get("/api/v1/cover-settings")
async def get_cover_prefs(user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.cover_settings import get_cover_settings

    return await get_cover_settings(str(user["id"]))


@app.post("/api/v1/cover-settings")
async def set_cover_prefs(request: Request, user: Any = Depends(get_current_user)) -> dict[str, Any]:
    from brainycat.cover_settings import update_cover_settings

    body = await request.json()
    return await update_cover_settings(str(user["id"]), body)


def _enrichment_priority(region: dict | None) -> list[str]:
    """Given an ISBN region, return the optimal enrichment source order."""
    if not region:
        return ["google_books", "open_library", "amazon"]
    sources = region.get("best_sources", [])
    # Add national bibliography based on country
    countries = region.get("countries", [])
    if "FR" in countries:
        sources = ["bnf", *sources]
    elif "DE" in countries or "AT" in countries or "CH" in countries:
        sources = ["dnb", *sources]
    elif "GB" in countries or "UK" in countries:
        sources = ["british_library", *sources]
    elif "ES" in countries:
        sources = ["bne", *sources]
    elif "JP" in countries:
        sources = ["ndl", "rakuten", *sources]
    # Always include google_books as fallback
    if "google_books" not in sources:
        sources.append("google_books")
    return sources


@app.get("/api/v1/setup/status")
async def setup_status() -> dict[str, Any]:
    count = await db.fetch_one("SELECT count(*) as c FROM users")
    return {"needs_setup": count["c"] == 0}


@app.post("/api/v1/setup")
async def first_run_setup(body: dict[str, Any]) -> dict[str, Any]:
    """Create the first admin user. Only works when no users exist."""
    count = await db.fetch_one("SELECT count(*) as c FROM users")
    if count["c"] > 0:
        return {"error": "Setup already completed"}
    username = body.get("username", "").strip()
    password = body.get("password", "")
    if not username or len(password) < 4:
        return {"error": "Username and password (4+ chars) required"}
    from brainycat.auth import _upsert_user

    await _upsert_user(username, password=password, role="admin")
    return {"ok": True, "message": f"Admin user '{username}' created. You can now log in."}
