"""Plugin configuration — server URL and API key."""

from calibre.utils.config import JSONConfig

prefs = JSONConfig("plugins/brainycat_sync")
prefs.defaults["server_url"] = "http://localhost:8000"
prefs.defaults["api_key"] = ""


class ConfigWidget:
    """Qt config widget for plugin settings."""

    def __init__(self):
        from qt.core import QGridLayout, QLabel, QLineEdit, QWidget

        self.widget = QWidget()
        layout = QGridLayout()
        self.widget.setLayout(layout)

        layout.addWidget(QLabel("BrainyCat Server URL:"), 0, 0)
        self.server_url = QLineEdit(prefs["server_url"])
        self.server_url.setPlaceholderText("https://tools.ecb.pm/brainycat")
        layout.addWidget(self.server_url, 0, 1)

        layout.addWidget(QLabel("API Key:"), 1, 0)
        self.api_key = QLineEdit(prefs["api_key"])
        self.api_key.setPlaceholderText("bc_...")
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.api_key, 1, 1)

    def save_settings(self):
        prefs["server_url"] = self.server_url.text().strip()
        prefs["api_key"] = self.api_key.text().strip()
