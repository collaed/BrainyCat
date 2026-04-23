"""BrainyCat Sync — Calibre plugin for two-way sync with BrainyCat AI companion.

Install: Preferences → Plugins → Load plugin from file → brainycat-sync.zip
Configure: Set your BrainyCat server URL and API key in plugin settings.

Features:
- Push: Send library metadata to BrainyCat for AI enrichment
- Pull: Apply BrainyCat's enrichments (better ISBNs, descriptions, covers, genres) back to Calibre
- Open: Launch BrainyCat web UI for the selected book
"""

from calibre.customize import InterfaceActionBase


class BrainyCatSync(InterfaceActionBase):
    name = "BrainyCat Sync"
    description = "Sync enrichments between Calibre and BrainyCat AI reading companion"
    supported_platforms = ["windows", "osx", "linux"]
    author = "BrainyCat"
    version = (1, 0, 0)
    minimum_calibre_version = (5, 0, 0)
    actual_plugin = "calibre_plugins.brainycat_sync.action:BrainyCatAction"

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.brainycat_sync.config import ConfigWidget

        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
