# MCP Server

## Overview

BrainyCat exposes tools via the Model Context Protocol for AI assistant integration (Claude, GPT, etc.).

File: `brainycat/mcp_server.py` (12K lines)
Transport: stdio (run via SSH from MCP client)

## Setup

```json
// In MCP client config (Claude Desktop, Kiro, etc.)
{
  "mcpServers": {
    "brainycat": {
      "command": "ssh",
      "args": ["sake", "docker", "exec", "-i", "brainycat", "python3", "-m", "brainycat.mcp_server"]
    }
  }
}
```

Or from the infra MCP config (`/home/collaed/infra/mcp/config.json`):
```json
"brainycat": "ssh sake ... brainycat.mcp_server"
```

## Available Tools (22)

| Tool | What it does |
|------|-------------|
| `search_books` | Full-text + fuzzy search across library |
| `get_book` | Get full metadata for a specific book |
| `edit_book` | Update title, ISBN, description, tags |
| `delete_book` | Remove book + files |
| `similar_books` | pgvector embedding similarity search |
| `enrich_book` | Trigger enrichment for a specific book |
| `batch_enrich` | Enrich multiple books |
| `classify_book` | BISAC/Thema genre classification |
| `search_content` | Search inside book text (FTS) |
| `recap` | Generate summary/recap of a book |
| `ask_book` | RAG — ask questions about a book's content |
| `library_stats` | Current library statistics |
| `efficiency` | Enrichment efficiency metrics |
| `book_sources` | Show which sources enriched a book |
| `send_to_kindle` | Email book to Kindle address |
| `convert_tts` | Convert book to audiobook via TTS |
| `convert_format` | Format conversion (EPUB↔PDF↔MOBI) |
| `merge_authors` | Merge duplicate author records |
| `create_series` | Create series + link books |
| `taste_recommendations` | Get personalized recommendations |
| `epub_check` | Validate EPUB structure |
| `epub_lint` | Fix common EPUB issues |
| `count_pages` | Count pages in PDF |

## Authentication

The MCP server runs inside the container, so it has direct DB access (no HTTP auth needed). External MCP clients connect via SSH, which provides authentication.

For HTTP API access (non-MCP), routes use either:
- JWT cookie (browser sessions)
- `Authorization: Bearer <api_key>` header (API clients)
- The Caddy forward_auth flow (ecb.pm access — currently broken)

## Example Interaction

```
User: What diving books do I have?
→ MCP calls search_books(query="diving")
→ Returns 4 results with metadata

User: Enrich the Monty Halls one
→ MCP calls enrich_book(book_id="740f7f0b-...")
→ Triggers enrichment pipeline (currently broken due to API timeouts)

User: Send Freedive to my Kindle
→ MCP calls send_to_kindle(book_id="...")
→ Converts to MOBI if needed, emails to kindle address (untested)
```

## Implementation Details

The MCP server uses the `mcp` protocol (JSON-RPC over stdio):
- `initialize` → capabilities declaration
- `tools/list` → returns tool definitions with JSON Schema
- `tools/call` → executes tool, returns result

No streaming. No resources. No prompts. Just tools.

Each tool is a thin wrapper around the existing Python functions — `search_books` calls `books.search()`, `enrich_book` calls `metadata.enrich_book()`, etc.
