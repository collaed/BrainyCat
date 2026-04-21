#!/usr/bin/env python3
"""BrainyCat CLI — command-line interface for library management."""

from __future__ import annotations

import json
import os

import click
import httpx

BASE_URL = os.environ.get("BRAINYCAT_URL", "http://localhost:8000")
HEADERS = {"X-Auth-User": os.environ.get("BRAINYCAT_USER", "ecb")}


def _api(method: str, path: str, **kwargs: object) -> dict:
    with httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=30) as c:
        resp = getattr(c, method)(f"/api/v1{path}", **kwargs)
        return (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {"status": resp.status_code}
        )


@click.group()
def cli() -> None:
    """🐱 BrainyCat — your unified personal library."""


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
def upload(file_path: str) -> None:
    """Upload a book file."""
    with open(file_path, "rb") as f, httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=60) as c:
        resp = c.post("/api/v1/books/upload", files={"file": (os.path.basename(file_path), f)})
        data = resp.json()
    click.echo(json.dumps(data, indent=2))


@cli.command()
@click.argument("query")
def search(query: str) -> None:
    """Search the library."""
    data = _api("get", f"/books?q={query}")
    for b in data.get("books", []):
        click.echo(f"  {b['id'][:8]}  {b['title']}  [{', '.join(b.get('formats', []))}]")
    click.echo(f"\n{data.get('total', 0)} results")


@cli.command(name="send-to-kindle")
@click.argument("book_id")
def send_to_kindle(book_id: str) -> None:
    """Send a book to Kindle."""
    data = _api("post", f"/books/{book_id}/send-to-kindle")
    click.echo(json.dumps(data, indent=2))


@cli.command()
@click.argument("book_id")
def enrich(book_id: str) -> None:
    """Enrich book metadata."""
    data = _api("post", f"/books/{book_id}/enrich")
    click.echo(json.dumps(data, indent=2))


@cli.command()
def stats() -> None:
    """Show reading statistics."""
    data = _api("get", "/stats/overview")
    click.echo(f"Books finished: {data.get('total_finished', 0)}")
    click.echo(f"Current streak: {data.get('current_streak_days', 0)} days")


@cli.command(name="import")
@click.argument("source", type=click.Choice(["calibre", "goodreads", "audiobookshelf"]))
@click.option("--file", "file_path", help="Path to import file (metadata.db or CSV)")
def import_cmd(source: str, file_path: str | None) -> None:
    """Import from external source."""
    if source == "audiobookshelf":
        data = _api("post", "/import/audiobookshelf")
    elif source == "goodreads" and file_path:
        with open(file_path, "rb") as f, httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=120) as c:
            resp = c.post("/api/v1/import/goodreads", files={"file": f})
            data = resp.json()
    else:
        click.echo("Provide --file for this source")
        return
    click.echo(json.dumps(data, indent=2))


@cli.command()
def health() -> None:
    """Check server health."""
    data = _api("get", "/health")
    click.echo(json.dumps(data, indent=2))


if __name__ == "__main__":
    cli()
