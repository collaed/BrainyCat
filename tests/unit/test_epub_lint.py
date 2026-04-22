"""Tests for EPUB lint."""

from brainycat.epub_lint import lint_epub


# lint_epub is async and needs DB — test the module imports
def test_module_imports() -> None:
    from brainycat import epub_lint
    assert hasattr(epub_lint, "lint_epub")
