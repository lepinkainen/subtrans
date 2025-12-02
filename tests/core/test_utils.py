"""Tests for core.utils module."""


def test_cache_dir_exists():
    """CACHE_DIR should exist after import."""
    from subtrans.core.utils import CACHE_DIR

    assert CACHE_DIR.exists()
    assert CACHE_DIR.is_dir()


def test_console_available():
    """Console should be importable."""
    from subtrans.core.utils import console

    assert console is not None
