"""FastAPI application — all routes for BrainyCat."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from brainycat import (
    auth,
    books,
    db,
)
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


from starlette.middleware.base import BaseHTTPMiddleware


class NoCacheStatic(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


app.add_middleware(NoCacheStatic)
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
from brainycat.oauth import router as oauth_router  # noqa: E402
from brainycat.routes.admin import router as admin_router  # noqa: E402
from brainycat.routes.ai import router as ai_router  # noqa: E402
from brainycat.routes.auth import router as auth_router  # noqa: E402
from brainycat.routes.books import router as books_router  # noqa: E402
from brainycat.routes.catalog import router as catalog_router  # noqa: E402
from brainycat.routes.enrichment import router as enrichment_router  # noqa: E402
from brainycat.routes.health import router as health_router  # noqa: E402
from brainycat.routes.kobo import router as kobo_router  # noqa: E402
from brainycat.routes.kosync import router as kosync_router  # noqa: E402
from brainycat.routes.media import router as media_router  # noqa: E402
from brainycat.routes.reader import router as reader_router  # noqa: E402
from brainycat.routes.social import router as social_router  # noqa: E402
from brainycat.routes.webdav import router as webdav_router  # noqa: E402
from brainycat.routes.ws import router as ws_router  # noqa: E402

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
app.include_router(kosync_router)
app.include_router(ws_router)
app.include_router(kobo_router)
app.include_router(oauth_router)
app.include_router(health_router)
app.include_router(webdav_router)


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
