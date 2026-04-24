"""Tests for federated social layer."""

from brainycat.social import decode_profile_hash, generate_profile_hash


def test_generate_hash() -> None:
    result = generate_profile_hash("localhost:8000", "admin")
    assert "hash" in result
    assert "public_key" in result
    assert len(result["hash"]) > 10


def test_roundtrip_hash() -> None:
    result = generate_profile_hash("localhost:8000", "admin")
    decoded = decode_profile_hash(result["hash"])
    assert decoded is not None
    assert decoded["server_url"] == "localhost:8000"
    assert decoded["username"] == "admin"
    assert decoded["public_key"] == result["public_key"]


def test_decode_invalid_hash() -> None:
    assert decode_profile_hash("not-valid") is None
    assert decode_profile_hash("") is None


def test_decode_wrong_prefix() -> None:
    import base64
    bad = base64.urlsafe_b64encode(b"http://wrong|user|key").decode()
    assert decode_profile_hash(bad) is None


def test_decode_missing_parts() -> None:
    import base64
    bad = base64.urlsafe_b64encode(b"bc://server|user").decode()
    assert decode_profile_hash(bad) is None
