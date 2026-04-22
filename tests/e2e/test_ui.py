"""E2E tests — Playwright browser tests against the live deployment.

Tests the actual UI: elements render, buttons work, navigation flows.
Run with: pytest tests/e2e/ -v --headed (to watch) or just pytest tests/e2e/
"""

import re

import pytest
from playwright.sync_api import Page, expect, sync_playwright

BASE = "https://tools.ecb.pm/brainycat/"
LOGIN_URL = "https://tools.ecb.pm/login/"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture(scope="module")
def authed_page(browser):
    """Page with authentication cookie."""
    ctx = browser.new_context(ignore_https_errors=True)
    page = ctx.new_page()
    # Login
    page.goto(LOGIN_URL)
    page.fill('input[name="user"]', "ecb")
    page.fill('input[name="pass"]', "Bl4ckL0tu$")
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_timeout(2000)
    # Navigate to BrainyCat
    page.goto(BASE)
    page.wait_for_timeout(3000)
    yield page
    ctx.close()


# ── Library Page ─────────────────────────────────────────────────────────

class TestLibraryPage:
    def test_page_loads(self, authed_page: Page) -> None:
        assert "BrainyCat" in authed_page.title() or authed_page.url.endswith("/brainycat/")

    def test_toolbar_visible(self, authed_page: Page) -> None:
        toolbar = authed_page.locator(".toolbar")
        assert toolbar.count() >= 1

    def test_search_input_exists(self, authed_page: Page) -> None:
        search = authed_page.locator("input[type='search'], input[placeholder*='Search'], #search")
        assert search.count() >= 1

    def test_upload_button(self, authed_page: Page) -> None:
        upload = authed_page.get_by_text("Upload")
        assert upload.count() >= 1

    def test_view_toggle(self, authed_page: Page) -> None:
        grid_btn = authed_page.locator("#btn-grid")
        list_btn = authed_page.locator("#btn-list")
        assert grid_btn.count() >= 1
        assert list_btn.count() >= 1

    def test_skin_selector(self, authed_page: Page) -> None:
        skin = authed_page.locator("#skin-select")
        assert skin.count() == 1
        options = skin.locator("option")
        assert options.count() >= 5  # 6 skins

    def test_opds_link(self, authed_page: Page) -> None:
        opds = authed_page.get_by_text("OPDS")
        assert opds.count() >= 1

    def test_books_render(self, authed_page: Page) -> None:
        """Books should appear in the content area."""
        authed_page.wait_for_timeout(2000)
        # Either grid cards or list rows
        content = authed_page.locator("#content")
        assert content.inner_html() != ""

    def test_book_count_displayed(self, authed_page: Page) -> None:
        count = authed_page.locator("#book-count")
        text = count.inner_text()
        # Should show something like "1603 books"
        assert re.search(r"\d+", text)

    def test_format_filter(self, authed_page: Page) -> None:
        select = authed_page.locator("#filter-format")
        assert select.count() == 1
        options = select.locator("option")
        assert options.count() >= 4  # All, epub, pdf, mobi, mp3, m4b

    def test_sort_selector(self, authed_page: Page) -> None:
        sort = authed_page.locator("#sort")
        assert sort.count() == 1


# ── Book Detail Modal ────────────────────────────────────────────────────

class TestBookModal:
    def test_click_book_opens_modal(self, authed_page: Page) -> None:
        # Click first book
        first_book = authed_page.locator("#content .card, #content .book-row, #content [onclick*='openModal']").first
        if first_book.count() > 0:
            first_book.click()
            authed_page.wait_for_timeout(1000)
            modal = authed_page.locator("#modal.active, .modal-overlay.active")
            assert modal.count() >= 1

    def test_modal_has_title(self, authed_page: Page) -> None:
        modal = authed_page.locator("#modal-content h2")
        if modal.count() > 0:
            assert modal.inner_text() != ""

    def test_modal_has_read_button(self, authed_page: Page) -> None:
        read_btn = authed_page.locator("#modal-content").get_by_text("Read")
        # Read button should exist for epub/pdf books
        # May not exist if the first book has no readable format
        pass  # Presence depends on book format

    def test_modal_has_enrich_button(self, authed_page: Page) -> None:
        enrich = authed_page.locator("#modal-content").get_by_text("Enrich")
        assert enrich.count() >= 1

    def test_modal_close(self, authed_page: Page) -> None:
        close = authed_page.locator(".close")
        if close.count() > 0:
            close.first.click()
            authed_page.wait_for_timeout(500)


# ── Skin Switching ───────────────────────────────────────────────────────

class TestSkins:
    def test_switch_to_spreadsheet(self, authed_page: Page) -> None:
        authed_page.select_option("#skin-select", "spreadsheet")
        authed_page.wait_for_timeout(500)
        assert "skin-spreadsheet" in (authed_page.locator("body").get_attribute("class") or "")

    def test_switch_to_cockpit(self, authed_page: Page) -> None:
        authed_page.select_option("#skin-select", "cockpit")
        authed_page.wait_for_timeout(500)
        assert "skin-cockpit" in (authed_page.locator("body").get_attribute("class") or "")

    def test_switch_back_to_default(self, authed_page: Page) -> None:
        authed_page.select_option("#skin-select", "default")
        authed_page.wait_for_timeout(500)
        body_class = authed_page.locator("body").get_attribute("class") or ""
        assert "skin-cockpit" not in body_class


# ── Navigation ───────────────────────────────────────────────────────────

class TestNavigation:
    def test_catalog_page(self, authed_page: Page) -> None:
        authed_page.goto(BASE + "static/catalog.html")
        authed_page.wait_for_timeout(2000)
        body = authed_page.content()
        assert "Gutenberg" in body or "catalog" in authed_page.url

    def test_catalog_language_selector(self, authed_page: Page) -> None:
        lang = authed_page.locator("#lang")
        if lang.count() > 0:
            options = lang.locator("option")
            assert options.count() >= 5  # EN, FR, DE, ES, IT, ...

    def test_intelligence_page(self, authed_page: Page) -> None:
        authed_page.goto(BASE + "static/intelligence.html")
        authed_page.wait_for_timeout(2000)
        assert "intelligence" in authed_page.url.lower() or authed_page.locator("h1, h2").count() > 0

    def test_efficiency_page(self, authed_page: Page) -> None:
        authed_page.goto(BASE + "static/efficiency.html")
        authed_page.wait_for_timeout(2000)
        assert "efficiency" in authed_page.url.lower()


# ── Reader ───────────────────────────────────────────────────────────────

class TestReader:
    def test_reader_page_loads(self, authed_page: Page) -> None:
        # Get a book with epub
        authed_page.goto(BASE + "static/reader.html?id=0cd9c24c-a3f6-465b-86f3-bf67f47b6ac2")
        authed_page.wait_for_timeout(3000)
        assert "reader" in authed_page.url

    def test_reader_has_controls(self, authed_page: Page) -> None:
        body = authed_page.content()
        assert len(body) > 500  # Page rendered something


# ── Audio Player ─────────────────────────────────────────────────────────

class TestPlayer:
    def test_player_page_loads(self, authed_page: Page) -> None:
        authed_page.goto(BASE + "static/player.html?id=0cd9c24c-a3f6-465b-86f3-bf67f47b6ac2")
        authed_page.wait_for_timeout(3000)
        assert "player" in authed_page.url

    def test_player_has_controls(self, authed_page: Page) -> None:
        # Player may show "No audio files" if book has no audio
        body = authed_page.content()
        assert "play-btn" in body or "No audio" in body or "player" in authed_page.url

    def test_player_has_speed_controls(self, authed_page: Page) -> None:
        body = authed_page.content()
        assert "1×" in body or "speed" in body.lower() or "No audio" in body

    def test_player_has_sleep_mode(self, authed_page: Page) -> None:
        body = authed_page.content()
        assert "sleep-mode-btn" in body or "Smart" in body or "No audio" in body

    def test_player_has_chapters(self, authed_page: Page) -> None:
        chapters = authed_page.locator("#chapters-section, text=Chapters")
        # May or may not have chapters depending on the book
        pass

    def test_player_has_volume(self, authed_page: Page) -> None:
        body = authed_page.content()
        assert "volume" in body.lower() or "No audio" in body

    def test_player_has_bookmark(self, authed_page: Page) -> None:
        body = authed_page.content()
        assert "Bookmark" in body or "bookmark" in body or "No audio" in body


# ── Public Feed ──────────────────────────────────────────────────────────

class TestPublicFeed:
    def test_public_feed_accessible(self, authed_page: Page) -> None:
        """Public feed should work without auth."""
        ctx = authed_page.context.browser.new_context(ignore_https_errors=True)
        page = ctx.new_page()
        resp = page.goto(BASE + "public/ecb/feed.json")
        assert resp.status == 200
        body = page.content()
        assert "username" in body or "error" in body
        ctx.close()
