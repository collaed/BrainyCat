"""Main plugin action — toolbar button and sync logic."""

import webbrowser
from functools import partial
from urllib.parse import quote

from calibre.gui2 import error_dialog, info_dialog
from calibre.gui2.actions import InterfaceAction
from calibre_plugins.brainycat_sync.config import prefs

try:
    from urllib.request import Request, urlopen
    import json
except ImportError:
    pass


class BrainyCatAction(InterfaceAction):
    name = "BrainyCat Sync"
    action_spec = ("BrainyCat", None, "Sync with BrainyCat AI companion", None)
    action_type = "current"

    def genesis(self):
        icon = get_icons("images/brainycat.png", "BrainyCat Sync")  # noqa: F821
        self.qaction.setIcon(icon)
        self.qaction.triggered.connect(self.show_menu)

        self.menu = self.qaction.menu()
        self.create_menu_action(self.menu, "Sync Enrichments", "Pull enrichments from BrainyCat", triggered=self.sync_enrichments)
        self.create_menu_action(self.menu, "Push Library", "Send selected books to BrainyCat", triggered=self.push_selected)
        self.create_menu_action(self.menu, "Open in BrainyCat", "Open selected book in browser", triggered=self.open_in_browser)
        self.menu.addSeparator()
        self.create_menu_action(self.menu, "Sync All Pending", "Apply all pending enrichments", triggered=self.sync_all)

    def show_menu(self):
        self.menu.popup(self.gui.cursor().pos())

    def _api(self, path, method="GET", data=None):
        """Call BrainyCat API."""
        url = prefs["server_url"].rstrip("/") + path
        headers = {"Authorization": f"Bearer {prefs['api_key']}", "Content-Type": "application/json"}
        req = Request(url, headers=headers, method=method)
        if data:
            req.data = json.dumps(data).encode()
        try:
            resp = urlopen(req, timeout=30)
            return json.loads(resp.read())
        except Exception as e:
            return {"error": str(e)}

    def sync_enrichments(self):
        """Pull pending enrichments from BrainyCat and apply to Calibre."""
        db = self.gui.current_db.new_api
        library_path = self.gui.current_db.library_path

        result = self._api(f"/api/v1/calibre/pending?library_path={quote(library_path)}")
        if "error" in result:
            return error_dialog(self.gui, "BrainyCat Sync", f"Error: {result['error']}", show=True)

        pending = result.get("pending", [])
        if not pending:
            return info_dialog(self.gui, "BrainyCat Sync", "No pending enrichments.", show=True)

        applied = 0
        for item in pending:
            book_id = item.get("calibre_id")
            if not book_id:
                continue
            try:
                if item.get("isbn"):
                    db.set_field("identifiers", {book_id: {"isbn": item["isbn"]}})
                if item.get("description"):
                    db.set_field("comments", {book_id: item["description"]})
                if item.get("rating"):
                    db.set_field("rating", {book_id: item["rating"]})
                if item.get("tags"):
                    existing = db.field_for("tags", book_id) or ()
                    db.set_field("tags", {book_id: list(set(existing) | set(item["tags"]))})
                if item.get("cover_url"):
                    import urllib.request
                    cover_data = urllib.request.urlopen(item["cover_url"], timeout=10).read()
                    db.set_cover({book_id: cover_data})
                applied += 1
            except Exception:
                pass

        # Acknowledge applied enrichments
        self._api("/api/v1/calibre/ack", method="POST", data={"ids": [p.get("id") for p in pending[:applied]]})

        self.gui.library_view.model().refresh()
        info_dialog(self.gui, "BrainyCat Sync", f"Applied {applied} enrichments to {len(pending)} books.", show=True)

    def push_selected(self):
        """Push selected books' metadata to BrainyCat."""
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows:
            return error_dialog(self.gui, "BrainyCat Sync", "No books selected.", show=True)

        db = self.gui.current_db.new_api
        books = []
        for row in rows:
            book_id = self.gui.library_view.model().id(row)
            mi = db.get_metadata(book_id)
            books.append({
                "calibre_id": book_id,
                "title": mi.title,
                "authors": list(mi.authors or []),
                "isbn": mi.isbn,
                "description": mi.comments,
                "tags": list(mi.tags or []),
                "series": mi.series,
                "series_index": mi.series_index,
                "publisher": mi.publisher,
                "language": str(mi.language) if mi.language else None,
                "identifiers": dict(mi.identifiers or {}),
            })

        result = self._api("/api/v1/calibre/push", method="POST", data={"books": books})
        if "error" in result:
            return error_dialog(self.gui, "BrainyCat Sync", f"Error: {result['error']}", show=True)

        info_dialog(self.gui, "BrainyCat Sync", f"Pushed {len(books)} books to BrainyCat.", show=True)

    def open_in_browser(self):
        """Open selected book in BrainyCat web UI."""
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows:
            return
        book_id = self.gui.library_view.model().id(rows[0])
        db = self.gui.current_db.new_api
        mi = db.get_metadata(book_id)
        # Search by title in BrainyCat
        url = f"{prefs['server_url']}/?q={quote(mi.title)}"
        webbrowser.open(url)

    def sync_all(self):
        """Sync all pending enrichments."""
        self.sync_enrichments()
