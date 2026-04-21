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
    secret_key: str = "change-me-in-production"
    session_max_age: int = 86400 * 7  # 7 days

    # External services
    intello_url: str = "http://intello:8000"
    signal_api_url: str = "http://signal-api:8080"
    smtp_host: str = "mailserver"
    smtp_port: int = 587

    # TTS / STT
    piper_voice: str = "en_US-lessac-medium"
    whisper_model: str = "small"

    # Embedding
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384

    model_config = {"env_prefix": "BRAINYCAT_"}


settings = Settings()
