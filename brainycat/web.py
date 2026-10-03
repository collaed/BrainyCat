"""FastAPI application — all routes for BrainyCat."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

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
    """App startup/shutdown: set up logging, open the DB pool, seed users, and start the scheduler. Invoked by FastAPI via the `lifespan` argument."""
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
    """Redirect to setup if no account has a password set yet, otherwise to library."""
    count = await db.fetch_one("SELECT count(*) as c FROM users WHERE password_hash IS NOT NULL")
    if count["c"] == 0:
        return RedirectResponse(url="./static/setup.html")
    return RedirectResponse(url="./static/index.html")


from starlette.middleware.base import BaseHTTPMiddleware


class NoCacheStatic(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        """Add no-cache headers to responses under /static/ so edited files aren't served stale. Called by Starlette's middleware chain on every request."""
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


app.add_middleware(NoCacheStatic)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup() -> None:
    """Initialize the shared HTTP client and pre-seed rate-limit backoffs. Run by FastAPI's startup event."""
    get_client()  # Initialize shared client
    from brainycat.rate_limit import seed_from_db

    await seed_from_db()  # Pre-set backoffs from recent failure history


@app.on_event("shutdown")
async def shutdown() -> None:
    """Close the shared HTTP client on app shutdown. Run by FastAPI's shutdown event."""
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
from brainycat.routes.triage import router as triage_router  # noqa: E402
from brainycat.routes.verify import router as verify_router  # noqa: E402
from brainycat.routes.webdav import router as webdav_router  # noqa: E402
from brainycat.routes.wanted import router as wanted_router  # noqa: E402
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
app.include_router(wanted_router)
# Mount the triage + verify review pages' APIs (Blocker 2: their routers existed but were never
# included, so static/triage.html and static/verify.html 404'd on every call).
app.include_router(triage_router)
app.include_router(verify_router)


@app.get("/catalog")
async def public_catalog():
    """Public library catalog (no auth required)."""
    from fastapi.responses import FileResponse

    return FileResponse("static/catalog-public.html")


# ── Health ────────────────────────────────────────────────────────────────
@app.get("/api/v1/health")
async def health() -> dict[str, Any]:
    """Report app/DB health status. GET /api/v1/health, used for monitoring/liveness checks."""
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


@app.get("/api/v1/authors")
async def list_authors(_u: Any = Depends(get_current_user)) -> list[dict[str, Any]]:
    """List all authors with their book counts, most-published first. GET /api/v1/authors; no frontend caller found in static/*.html."""
    rows = await db.fetch_all(
        "SELECT a.id, a.name, count(ba.book_id) as book_count "
        "FROM authors a JOIN books_authors ba ON ba.author_id = a.id "
        "GROUP BY a.id ORDER BY count(ba.book_id) DESC, a.name"
    )
    return [dict(r) for r in rows]


# ── Author update
@app.get("/api/v1/setup/status")
async def setup_status() -> dict[str, Any]:
    """needs_setup is about a *usable* (password-set) account, not raw row count — seed_users()
    creates a passwordless 'admin' placeholder at every startup (for the X-Auth-User header path),
    which would otherwise make this always report false on every fresh install."""
    count = await db.fetch_one("SELECT count(*) as c FROM users WHERE password_hash IS NOT NULL")
    return {"needs_setup": count["c"] == 0}


@app.post("/api/v1/setup")
async def first_run_setup(body: dict[str, Any]) -> dict[str, Any]:
    """Create (or complete) the first admin account. Only works while no account has a password set."""
    count = await db.fetch_one("SELECT count(*) as c FROM users WHERE password_hash IS NOT NULL")
    if count["c"] > 0:
        return {"error": "Setup already completed"}
    username = body.get("username", "").strip()
    password = body.get("password", "")
    if not username or len(password) < 4:
        return {"error": "Username and password (4+ chars) required"}
    import bcrypt

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    await db.execute(
        """INSERT INTO users (username, password_hash, role) VALUES ($1, $2, 'admin')
           ON CONFLICT (username) DO UPDATE SET password_hash = $2, role = 'admin'""",
        username,
        password_hash,
    )
    return {"ok": True, "message": f"Admin user '{username}' created. You can now log in."}
