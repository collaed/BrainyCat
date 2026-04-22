"""Tests for multi-source aggregator."""
def test_module_exists() -> None:
    import importlib
    spec = importlib.util.find_spec("brainycat.aggregator")
    assert spec is not None
