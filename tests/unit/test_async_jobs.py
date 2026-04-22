"""Tests for async jobs module."""

from brainycat.async_jobs import submit_job, check_job, list_jobs


def test_module_imports() -> None:
    assert callable(submit_job)
    assert callable(check_job)
    assert callable(list_jobs)
