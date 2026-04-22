"""Plugin system — auto-discover and run Python plugins from plugins/ directory.

Plugins are Python files in the plugins/ directory that define a class
inheriting from BrainyCatPlugin. They register hooks that fire on events.

Hooks: on_upload, on_enrich, on_search, on_convert, on_schedule, on_delete
Plugins can also register custom API routes via register_routes().
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any


class BrainyCatPlugin:
    """Base class for plugins."""

    name: str = "unnamed"
    version: str = "0.1"
    description: str = ""

    def on_upload(self, book_id: str, metadata: dict) -> None:
        pass

    def on_enrich(self, book_id: str, source: str, data: dict) -> None:
        pass

    def on_delete(self, book_id: str) -> None:
        pass

    def on_schedule(self) -> None:
        """Called every scheduler cycle (~15s)."""
        pass

    def register_routes(self, app: Any) -> None:
        """Register custom FastAPI routes."""
        pass


_plugins: list[BrainyCatPlugin] = []


def discover_plugins(plugin_dir: str = "/app/plugins") -> list[dict[str, str]]:
    """Discover and load plugins from directory."""
    global _plugins
    _plugins = []
    loaded = []

    if not os.path.isdir(plugin_dir):
        return []

    for fname in sorted(os.listdir(plugin_dir)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        path = os.path.join(plugin_dir, fname)
        try:
            spec = importlib.util.spec_from_file_location(fname[:-3], path)
            if not spec or not spec.loader:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            for attr in dir(mod):
                obj = getattr(mod, attr)
                if isinstance(obj, type) and issubclass(obj, BrainyCatPlugin) and obj is not BrainyCatPlugin:
                    plugin = obj()
                    _plugins.append(plugin)
                    loaded.append({"name": plugin.name, "version": plugin.version, "description": plugin.description})
        except Exception as e:
            loaded.append({"name": fname, "error": str(e)[:100]})

    return loaded


def fire_hook(hook: str, **kwargs: Any) -> None:
    """Fire a hook on all loaded plugins."""
    for plugin in _plugins:
        try:
            method = getattr(plugin, hook, None)
            if method:
                method(**kwargs)
        except Exception:
            pass


def get_plugins() -> list[dict[str, str]]:
    return [{"name": p.name, "version": p.version, "description": p.description} for p in _plugins]
