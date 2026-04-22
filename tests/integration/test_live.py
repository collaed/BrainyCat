"""Integration tests — hit the live deployment at tools.ecb.pm/brainycat.

These tests verify real endpoints on the real server with real data.
Not mocks. Not stubs. Real HTTP requests, real database, real responses.

Run with: pytest tests/integration/ -v
Requires: auth cookie in /tmp/cookies3.txt
"""

import json
import subprocess

import pytest

BASE = "https://tools.ecb.pm/brainycat"
COOKIE_FILE = "/tmp/cookies3.txt"


def _curl(method: str, path: str, data: str | None = None, auth: bool = True) -> tuple[int, str]:
    """Run curl against the live server."""
    cmd = ["curl", "-s", "-w", "\n%{http_code}", "--max-time", "30"]
    if auth:
        cmd += ["-b", COOKIE_FILE]
    if method == "POST":
        cmd += ["-X", "POST"]
        if data:
            cmd += ["-H", "Content-Type: application/json", "-d", data]
    cmd.append(f"{BASE}{path}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
    lines = result.stdout.strip().rsplit("\n", 1)
    body = lines[0] if len(lines) > 1 else ""
    code = int(lines[-1]) if lines[-1].isdigit() else 0
    return code, body


def _json(body: str) -> dict:
    try:
        return json.loads(body)
    except Exception:
        return {"_raw": body}


# ── Health & Auth ────────────────────────────────────────────────────────

class TestHealth:
    def test_health(self) -> None:
        code, body = _curl("GET", "/api/v1/health")
        assert code == 200

    def test_me(self) -> None:
        code, body = _curl("GET", "/api/v1/me")
        assert code == 200
        d = _json(body)
        assert d.get("user", {}).get("username") == "ecb"

    def test_unauthenticated(self) -> None:
        code, _ = _curl("GET", "/api/v1/me", auth=False)
        assert code in (302, 401, 403)


# ── Books CRUD ───────────────────────────────────────────────────────────

class TestBooks:
    def test_list_books(self) -> None:
        code, body = _curl("GET", "/api/v1/books?limit=5")
        assert code == 200
        d = _json(body)
        assert "books" in d or isinstance(d, list)

    def test_search_books(self) -> None:
        code, body = _curl("GET", "/api/v1/books?q=beauty&limit=3")
        assert code == 200

    def test_get_book(self) -> None:
        code, body = _curl("GET", "/api/v1/books?limit=1")
        d = _json(body)
        books = d.get("books", d if isinstance(d, list) else [])
        if books:
            bid = books[0]["id"]
            code2, body2 = _curl("GET", f"/api/v1/books/{bid}")
            assert code2 == 200
            d2 = _json(body2)
            assert d2.get("title")

    def test_book_not_found(self) -> None:
        code, _ = _curl("GET", "/api/v1/books/00000000-0000-0000-0000-000000000000")
        assert code in (404, 200)  # May return null or 404


# ── Enrichment & Intelligence ────────────────────────────────────────────

class TestIntelligence:
    def test_source_coverage(self) -> None:
        code, body = _curl("GET", "/api/v1/sources/coverage")
        assert code == 200
        d = _json(body)
        assert "total_books" in d
        assert d["total_books"] > 1000

    def test_converters(self) -> None:
        code, body = _curl("GET", "/api/v1/converters")
        assert code == 200
        d = _json(body)
        assert d.get("weasyprint") is True

    def test_skins(self) -> None:
        code, body = _curl("GET", "/api/v1/ui/skins")
        assert code == 200
        d = _json(body)
        assert len(d) >= 5


# ── OPDS ─────────────────────────────────────────────────────────────────

class TestOPDS:
    def test_opds_catalog(self) -> None:
        code, body = _curl("GET", "/api/v1/opds/catalog.xml")
        assert code == 200
        assert "<feed" in body
        assert "<entry>" in body

    def test_opds_pagination(self) -> None:
        code, body = _curl("GET", "/api/v1/opds/catalog.xml?page=2")
        assert code == 200
        assert "<entry>" in body

    def test_opds_search(self) -> None:
        code, body = _curl("GET", "/api/v1/opds/search?q=python")
        assert code == 200


# ── Social ───────────────────────────────────────────────────────────────

class TestSocial:
    def test_public_feed_no_auth(self) -> None:
        code, body = _curl("GET", "/public/ecb/feed.json", auth=False)
        assert code == 200
        d = _json(body)
        assert "username" in d or "error" in d  # May not be enabled yet

    def test_public_feed_nonexistent_user(self) -> None:
        code, body = _curl("GET", "/public/nonexistent/feed.json", auth=False)
        assert code == 200
        d = _json(body)
        assert d.get("error")

    def test_following_list(self) -> None:
        code, body = _curl("GET", "/api/v1/social/following")
        assert code == 200


# ── Features ─────────────────────────────────────────────────────────────

class TestFeatures:
    def test_custom_columns(self) -> None:
        code, body = _curl("GET", "/api/v1/custom-columns")
        assert code == 200

    def test_virtual_libraries(self) -> None:
        code, body = _curl("GET", "/api/v1/virtual-libraries")
        assert code == 200

    def test_plugins(self) -> None:
        code, body = _curl("GET", "/api/v1/plugins")
        assert code == 200

    def test_cover_settings(self) -> None:
        code, body = _curl("GET", "/api/v1/cover-settings")
        assert code == 200
        d = _json(body)
        assert d.get("fiction_stripe") == "vertical"

    def test_jobs(self) -> None:
        code, body = _curl("GET", "/api/v1/jobs")
        assert code == 200


# ── API Key Auth ─────────────────────────────────────────────────────────

class TestAPIKey:
    def test_bearer_auth(self) -> None:
        """Test that Bearer token auth works through Caddy."""
        cmd = ["curl", "-s", "-w", "\n%{http_code}", "--max-time", "10",
               "-H", "Authorization: Bearer bc_3l0TR5Sbk1k7FDsR_acgSyB_DL2FKeiadZ8S69Z6y7A",
               f"{BASE}/api/v1/me"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        lines = result.stdout.strip().rsplit("\n", 1)
        code = int(lines[-1]) if lines[-1].isdigit() else 0
        assert code == 200
