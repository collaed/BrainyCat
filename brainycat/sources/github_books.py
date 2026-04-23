"""GitHub ebook discovery — find free/open ebooks in public repositories.

Searches for EPUB/PDF files in public repos, filtering for repos with
permissive licenses (CC, MIT, Apache, public domain, unlicense).
Also searches curated "awesome" lists of free books.
"""

from __future__ import annotations

from typing import Any

from brainycat.http_client import get_client

API = "https://api.github.com"
PERMISSIVE_LICENSES = {"mit", "apache-2.0", "cc0-1.0", "unlicense", "cc-by-4.0", "cc-by-sa-4.0", "gpl-3.0", "lgpl-3.0"}


async def search_ebooks(query: str, language: str = "", limit: int = 20) -> dict[str, Any]:
    """Search GitHub for repos containing free ebooks."""
    # Strategy 1: Search repos with "ebook" or "book" + query + permissive license
    search_query = f"{query} ebook OR book OR epub in:name,description,readme"
    if language:
        search_query += f" language:{language}"

    try:
        client = get_client()
        resp = await client.get(
            f"{API}/search/repositories",
            params={"q": search_query, "sort": "stars", "per_page": limit},
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        if resp.status_code != 200:
            return {"books": [], "error": f"GitHub API: {resp.status_code}"}

        data = resp.json()
        books = []
        for repo in data.get("items", []):
            license_key = (repo.get("license") or {}).get("key", "")
            books.append(
                {
                    "source": "github",
                    "title": repo["name"],
                    "description": (repo.get("description") or "")[:200],
                    "authors": [repo["owner"]["login"]],
                    "url": repo["html_url"],
                    "stars": repo["stargazers_count"],
                    "license": license_key,
                    "is_permissive": license_key in PERMISSIVE_LICENSES,
                    "topics": repo.get("topics", []),
                    "updated": repo.get("updated_at"),
                }
            )

        return {"count": data.get("total_count", 0), "books": books}
    except Exception as e:
        return {"books": [], "error": str(e)[:100]}


async def search_awesome_lists(topic: str = "books") -> dict[str, Any]:
    """Search GitHub's curated awesome-lists for free book collections."""
    try:
        client = get_client()
        resp = await client.get(
            f"{API}/search/repositories",
            params={"q": f"awesome {topic} free in:name,description", "sort": "stars", "per_page": 10},
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        if resp.status_code != 200:
            return {"lists": []}

        data = resp.json()
        return {
            "lists": [
                {
                    "name": r["name"],
                    "description": (r.get("description") or "")[:200],
                    "url": r["html_url"],
                    "stars": r["stargazers_count"],
                }
                for r in data.get("items", [])
            ]
        }
    except Exception:
        return {"lists": []}


async def find_epub_files(repo_owner: str, repo_name: str) -> list[dict[str, Any]]:
    """Find EPUB/PDF files in a specific GitHub repo."""
    try:
        client = get_client()
        resp = await client.get(
            f"{API}/search/code",
            params={"q": f"extension:epub extension:pdf repo:{repo_owner}/{repo_name}"},
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        if resp.status_code != 200:
            return []

        data = resp.json()
        return [
            {
                "name": item["name"],
                "path": item["path"],
                "url": item["html_url"],
                "download_url": f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/main/{item['path']}",
            }
            for item in data.get("items", [])
            if item["name"].lower().endswith((".epub", ".pdf"))
        ]
    except Exception:
        return []
