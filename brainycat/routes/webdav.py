"""WebDAV-compatible endpoint for generic reader sync.

Supports PROPFIND (list) and GET (download) for WebDAV readers.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Request, Response

from brainycat import db

router = APIRouter(prefix="/api/v1/webdav", tags=["webdav"])


async def _auth_webdav(authorization: str | None) -> dict | None:
    """Basic auth for WebDAV."""
    if not authorization or not authorization.startswith("Basic "):
        return None
    import base64

    decoded = base64.b64decode(authorization[6:]).decode()
    username, _, key = decoded.partition(":")
    user = await db.fetch_one("SELECT id, username FROM users WHERE username = $1 AND api_key = $2", username, key)
    return dict(user) if user else None


@router.api_route("/books", methods=["GET", "PROPFIND"])
async def webdav_list(request: Request, authorization: str | None = Header(None)) -> Response:
    """List books as WebDAV collection (PROPFIND) or JSON (GET)."""
    user = await _auth_webdav(authorization)
    if not user:
        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="BrainyCat"'})

    books = await db.fetch_all(
        """SELECT b.id, b.title, bf.file_name, bf.format, bf.file_path
           FROM books b JOIN book_files bf ON bf.book_id = b.id
           WHERE bf.format IN ('epub', 'pdf')
           ORDER BY b.updated_at DESC LIMIT 200"""
    )

    if request.method == "PROPFIND":
        # Return WebDAV XML
        items = "\n".join(
            f"""<D:response><D:href>/api/v1/webdav/books/{r["id"]}/{r["file_name"]}</D:href>
            <D:propstat><D:prop><D:displayname>{r["title"]}</D:displayname>
            <D:getcontenttype>application/{r["format"]}</D:getcontenttype></D:prop>
            <D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"""
            for r in books
        )
        xml = f'<?xml version="1.0"?><D:multistatus xmlns:D="DAV:">{items}</D:multistatus>'
        return Response(content=xml, media_type="application/xml", status_code=207)

    return Response(
        content=str([{"id": str(r["id"]), "title": r["title"], "file": r["file_name"]} for r in books]),
        media_type="application/json",
    )


@router.get("/books/{book_id}/{filename}")
async def webdav_download(book_id: str, filename: str, authorization: str | None = Header(None)) -> Any:
    """Download a book file via WebDAV."""
    user = await _auth_webdav(authorization)
    if not user:
        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="BrainyCat"'})

    import os
    from uuid import UUID

    from fastapi.responses import FileResponse

    row = await db.fetch_one(
        "SELECT file_path, file_name FROM book_files WHERE book_id = $1 AND file_name = $2",
        UUID(book_id),
        filename,
    )
    if not row or not os.path.isfile(row["file_path"]):
        return Response(status_code=404)

    return FileResponse(row["file_path"], filename=row["file_name"])
