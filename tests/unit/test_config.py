"""Tests for config module."""

from brainycat.config import Settings


def test_settings_has_required_fields() -> None:
    fields = set(Settings.model_fields.keys())
    assert "database_url" in fields
    assert "data_dir" in fields
    assert "intello_url" in fields


def test_settings_env_prefix() -> None:
    assert Settings.model_config.get("env_prefix") == "BRAINYCAT_"


def test_settings_defaults() -> None:
    fields = Settings.model_fields
    assert fields["data_dir"].default == "/data/books"
    assert fields["embedding_dim"].default == 384
