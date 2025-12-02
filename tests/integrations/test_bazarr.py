"""Tests for integrations.bazarr module."""


def test_apply_path_mapping():
    """Path mapping should replace prefixes correctly."""
    from subtrans.integrations.bazarr import apply_path_mapping

    mappings = [("/volume1/movies", "/Volumes/NAS/movies")]
    result = apply_path_mapping("/volume1/movies/Action/test.mkv", mappings)
    assert result == "/Volumes/NAS/movies/Action/test.mkv"


def test_apply_path_mapping_no_match():
    """Unmapped paths should pass through unchanged."""
    from subtrans.integrations.bazarr import apply_path_mapping

    mappings = [("/volume1/movies", "/Volumes/NAS/movies")]
    result = apply_path_mapping("/other/path/test.mkv", mappings)
    assert result == "/other/path/test.mkv"


def test_apply_path_mapping_multiple():
    """Should try all mappings in order."""
    from subtrans.integrations.bazarr import apply_path_mapping

    mappings = [
        ("/volume1/movies", "/mnt/movies"),
        ("/volume2/tv", "/mnt/tv")
    ]
    result = apply_path_mapping("/volume2/tv/Show/s01e01.mkv", mappings)
    assert result == "/mnt/tv/Show/s01e01.mkv"


def test_apply_path_mapping_first_match_wins():
    """Should use first matching mapping."""
    from subtrans.integrations.bazarr import apply_path_mapping

    mappings = [
        ("/volume1", "/mnt1"),
        ("/volume1/movies", "/mnt/movies")
    ]
    result = apply_path_mapping("/volume1/movies/test.mkv", mappings)
    assert result == "/mnt1/movies/test.mkv"


def test_apply_path_mapping_empty_list():
    """Empty mapping list should return original path."""
    from subtrans.integrations.bazarr import apply_path_mapping

    result = apply_path_mapping("/test/path.mkv", [])
    assert result == "/test/path.mkv"
