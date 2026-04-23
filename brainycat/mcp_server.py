"""BrainyCat MCP Server — expose library operations to AI clients."""

from __future__ import annotations

import json
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from brainycat.http_client import get_client

# BrainyCat API — configure via environment
API_URL = os.environ.get("BRAINYCAT_URL", "http://localhost:8000") + "/api/v1"
API_KEY = os.environ.get("BRAINYCAT_API_KEY", "")
HEADERS: dict[str, str] = {}
if API_KEY:
    HEADERS["Authorization"] = f"Bearer {API_KEY}"
else:
    HEADERS["X-Auth-User"] = os.environ.get("BRAINYCAT_USER", "ecb")


async def _api(method: str, path: str, body: dict | None = None) -> dict:
    c = get_client()
    if method == "GET":
        r = await c.get(path)
    elif method == "PATCH":
        r = await c.patch(path, json=body) if body else await c.patch(path)
    else:
        r = await c.post(path, json=body) if body else await c.post(path)
    return r.json() if r.headers.get("content-type", "").startswith("application/json") else {"status": r.status_code}


app = Server("brainycat")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_books",
            description="Search the book library by title, author, ISBN, or tag",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                    "offset": {"type": "integer", "default": 0},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_book",
            description="Get full details of a book by ID",
            inputSchema={"type": "object", "properties": {"book_id": {"type": "string"}}, "required": ["book_id"]},
        ),
        Tool(
            name="similar_books",
            description="Find books similar to a given book",
            inputSchema={"type": "object", "properties": {"book_id": {"type": "string"}}, "required": ["book_id"]},
        ),
        Tool(
            name="enrich_book",
            description="Trigger metadata enrichment for a book from online sources",
            inputSchema={"type": "object", "properties": {"book_id": {"type": "string"}}, "required": ["book_id"]},
        ),
        Tool(
            name="classify_book",
            description="Use LLM to classify a book's genre (Thema codes)",
            inputSchema={"type": "object", "properties": {"book_id": {"type": "string"}}, "required": ["book_id"]},
        ),
        Tool(
            name="search_content",
            description="Semantic search within a book's content",
            inputSchema={
                "type": "object",
                "properties": {"book_id": {"type": "string"}, "query": {"type": "string"}},
                "required": ["book_id", "query"],
            },
        ),
        Tool(
            name="recap",
            description="Get an AI-generated recap of a book up to current reading position",
            inputSchema={"type": "object", "properties": {"book_id": {"type": "string"}}, "required": ["book_id"]},
        ),
        Tool(
            name="ask_book",
            description="Ask a question about a book (no spoilers)",
            inputSchema={
                "type": "object",
                "properties": {"book_id": {"type": "string"}, "question": {"type": "string"}},
                "required": ["book_id", "question"],
            },
        ),
        Tool(
            name="library_stats",
            description="Get library statistics (total books, genres, top authors)",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="efficiency",
            description="Get algorithm efficiency metrics (ISBN coverage, enrichment rates)",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="send_to_kindle",
            description="Send a book to Kindle via email",
            inputSchema={"type": "object", "properties": {"book_id": {"type": "string"}}, "required": ["book_id"]},
        ),
        Tool(
            name="convert_tts",
            description="Convert an ebook to audiobook using TTS",
            inputSchema={"type": "object", "properties": {"book_id": {"type": "string"}}, "required": ["book_id"]},
        ),
        Tool(
            name="merge_authors",
            description="Merge two duplicate authors (keep one, delete other)",
            inputSchema={
                "type": "object",
                "properties": {"keep_id": {"type": "string"}, "merge_id": {"type": "string"}},
                "required": ["keep_id", "merge_id"],
            },
        ),
        Tool(
            name="create_series",
            description="Create a book series and link books to it",
            inputSchema={
                "type": "object",
                "properties": {"series_name": {"type": "string"}, "book_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["series_name", "book_ids"],
            },
        ),
        Tool(
            name="edit_book",
            description="Edit book metadata (title, isbn, description)",
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "string"},
                    "title": {"type": "string"},
                    "isbn": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["book_id"],
            },
        ),
        Tool(
            name="delete_book",
            description="Delete a book from the library",
            inputSchema={"type": "object", "properties": {"book_id": {"type": "string"}}, "required": ["book_id"]},
        ),
        Tool(
            name="taste_recommendations",
            description="Get 5-category taste-based recommendations (DNA, Author, Community, Overlap, Anti)",
            inputSchema={"type": "object", "properties": {"user_id": {"type": "string"}}, "required": ["user_id"]},
        ),
        Tool(
            name="book_sources",
            description="Get side-by-side metadata from all enrichment sources for a book",
            inputSchema={"type": "object", "properties": {"book_id": {"type": "string"}}, "required": ["book_id"]},
        ),
        Tool(
            name="epub_check",
            description="Run quality check on an EPUB (structure, links, images)",
            inputSchema={"type": "object", "properties": {"book_id": {"type": "string"}}, "required": ["book_id"]},
        ),
        Tool(
            name="epub_lint",
            description="Lint an EPUB (CSS, images, fonts, accessibility)",
            inputSchema={"type": "object", "properties": {"book_id": {"type": "string"}}, "required": ["book_id"]},
        ),
        Tool(
            name="count_pages",
            description="Count pages and words in a book",
            inputSchema={"type": "object", "properties": {"book_id": {"type": "string"}}, "required": ["book_id"]},
        ),
        Tool(
            name="batch_enrich",
            description="Enrich multiple books at once (trigger metadata fetch from all sources)",
            inputSchema={
                "type": "object",
                "properties": {"book_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["book_ids"],
            },
        ),
        Tool(
            name="convert_format",
            description="Convert a book to another format (pdf, mobi, azw3, txt)",
            inputSchema={
                "type": "object",
                "properties": {"book_id": {"type": "string"}, "target_format": {"type": "string"}},
                "required": ["book_id", "target_format"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    result: dict[str, Any] = {}

    if name == "search_books":
        limit = arguments.get("limit", 20)
        offset = arguments.get("offset", 0)
        result = await _api("GET", f"/books?q={arguments['query']}&limit={limit}&offset={offset}")
    elif name == "get_book":
        result = await _api("GET", f"/books/{arguments['book_id']}")
    elif name == "similar_books":
        result = await _api("GET", f"/books/{arguments['book_id']}/similar")
    elif name == "enrich_book":
        result = await _api("POST", f"/books/{arguments['book_id']}/enrich")
    elif name == "classify_book":
        result = await _api("POST", f"/books/{arguments['book_id']}/classify")
    elif name == "search_content":
        result = await _api("GET", f"/books/{arguments['book_id']}/search-content?q={arguments['query']}")
    elif name == "recap":
        result = await _api("GET", f"/ai/recap/{arguments['book_id']}")
    elif name == "ask_book":
        result = await _api("POST", f"/ai/ask/{arguments['book_id']}", {"question": arguments["question"]})
    elif name == "library_stats":
        result = await _api("GET", "/stats/overview")
    elif name == "efficiency":
        result = await _api("GET", "/intelligence/efficiency")
    elif name == "send_to_kindle":
        result = await _api("POST", f"/books/{arguments['book_id']}/send-to-kindle")
    elif name == "convert_tts":
        result = await _api("POST", f"/books/{arguments['book_id']}/convert/tts")
    elif name == "merge_authors":
        result = await _api("POST", "/intelligence/merge-authors", {"keep_id": arguments["keep_id"], "merge_id": arguments["merge_id"]})
    elif name == "create_series":
        result = await _api(
            "POST", "/intelligence/apply-series", {"series_name": arguments["series_name"], "book_ids": arguments["book_ids"]}
        )
    elif name == "edit_book":
        body = {k: v for k, v in arguments.items() if k != "book_id" and v}
        result = await _api("PATCH", f"/books/{arguments['book_id']}", body)
    elif name == "delete_book":
        c = get_client()
        r = await c.delete(f"/books/{arguments['book_id']}")
        result = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"status": r.status_code}
    elif name == "taste_recommendations":
        result = await _api("GET", f"/recommendations/{arguments['user_id']}")
    elif name == "book_sources":
        result = await _api("GET", f"/books/{arguments['book_id']}/sources")
    elif name == "epub_check":
        result = await _api("POST", f"/books/{arguments['book_id']}/epub-check")
    elif name == "epub_lint":
        result = await _api("POST", f"/books/{arguments['book_id']}/epub-lint")
    elif name == "count_pages":
        result = await _api("POST", f"/books/{arguments['book_id']}/count-pages")
    elif name == "batch_enrich":
        result = await _api("POST", "/bulk/enrich", {"book_ids": arguments["book_ids"]})
    elif name == "convert_format":
        result = await _api("POST", f"/books/{arguments['book_id']}/convert/{arguments['target_format']}")
    elif name == "search_gutenberg":
        result = await _api("GET", f"/catalog/gutenberg/search?q={arguments['query']}")
    elif name == "search_librivox":
        result = await _api("GET", f"/catalog/librivox/search?q={arguments['query']}")
    elif name == "list_characters":
        result = await _api("POST", f"/books/{arguments['book_id']}/xray")
    elif name == "translate_book":
        result = await _api("POST", f"/books/{arguments['book_id']}/translate", {"target_lang": arguments["target_lang"]})
    elif name == "generate_cover":
        result = await _api("POST", f"/books/{arguments['book_id']}/generate-cover")

    # Wrap errors for better AI client experience
    if isinstance(result, dict) and result.get("detail"):
        result = {"error": result["detail"], "tool": name}
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main() -> None:
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
