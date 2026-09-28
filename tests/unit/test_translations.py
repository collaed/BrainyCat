"""Tests for the pure (non-network) parts of Wikidata translation linking."""

from brainycat.translations import _claim_target


def test_claim_target_extracts_entity_id() -> None:
    entity = {"claims": {"P629": [{"mainsnak": {"datavalue": {"value": {"id": "Q25338"}}}}]}}
    assert _claim_target(entity, "P629") == "Q25338"


def test_claim_target_missing_property() -> None:
    assert _claim_target({"claims": {}}, "P629") is None


def test_claim_target_malformed_claim() -> None:
    entity = {"claims": {"P629": [{"mainsnak": {"snaktype": "novalue"}}]}}
    assert _claim_target(entity, "P629") is None
