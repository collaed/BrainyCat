"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """BrainyCat configuration loaded from environment."""

    # Database
    database_url: str = "postgresql://brainycat:brainycat@postgres:5432/brainycat"

    # Paths
    data_dir: str = "/data/books"
    incoming_dir: str = "/data/incoming"

    # Auth
    secret_key: str = ""
    session_max_age: int = 86400 * 7  # 7 days

    def __init__(self, **kwargs: object) -> None:
        """Load settings, generating and persisting a random `secret_key` on first run if none is configured."""
        super().__init__(**kwargs)
        if not self.secret_key:
            import os
            import secrets

            key_file = os.path.join(os.path.dirname(self.data_dir), ".secret_key")
            if os.path.isfile(key_file):
                with open(key_file) as kf:
                    self.secret_key = kf.read().strip()
            else:
                self.secret_key = secrets.token_hex(32)
                os.makedirs(os.path.dirname(key_file), exist_ok=True)
                with open(key_file, "w") as f:
                    f.write(self.secret_key)

    # External services
    intello_url: str = "http://intello:8000"
    intello_heavy_url: str = ""  # For OCR/TTS/STT — falls back to intello_url
    intello_api_key: str = ""
    intello_heavy_api_key: str = ""  # Falls back to intello_api_key

    @property
    def heavy_url(self) -> str:
        """Intello URL to use for heavy jobs (OCR/TTS/STT), falling back to the default intello_url."""
        return self.intello_heavy_url or self.intello_url

    @property
    def heavy_key(self) -> str:
        """Intello API key to use for heavy jobs, falling back to the default intello_api_key."""
        return self.intello_heavy_api_key or self.intello_api_key
    signal_api_url: str = "http://signal-api:8080"
    smtp_host: str = "mailserver"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # defaults to smtp_user, then brainycat@{smtp_host}, if unset
    smtp_validate_certs: bool = True  # set false when smtp_host is a local relay/tunnel, not the real MX name
    resend_api_key: str = ""  # if set, Kindle/device delivery uses the Resend HTTP API instead of SMTP

    # Google Books
    google_books_api_key: str = ""

    # TTS / STT
    piper_voice: str = "en_US-lessac-medium"
    whisper_model: str = "small"

    # Embedding
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384

    model_config = {"env_prefix": "BRAINYCAT_"}

    # Experimental features (set to "1" to enable)
    exp_text_profile: str = "0"
    exp_lsh_dedup: str = "0"
    exp_isbntools: str = "0"
    exp_file_rename: str = "0"

    # Feature toggles
    enable_fts: bool = False

    # Email consumption (IMAP)
    imap_host: str = ""
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    enable_email_import: bool = False
    exp_kindle_fix: str = "0"
    exp_heatmap: str = "0"
    exp_mind_map: str = "0"
    exp_share_cards: str = "0"
    exp_pdf_embed: str = "0"
    readarr_url: str = ""
    readarr_api_key: str = ""
    readarr_root_folder: str = ""  # auto-detected from Readarr's own config if unset
    readarr_quality_profile_id: str = ""  # auto-detected (first available) if unset
    google_client_id: str = ""
    google_client_secret: str = ""
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""


settings = Settings()
