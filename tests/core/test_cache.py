"""Tests for core.cache module."""

from pathlib import Path
from subtrans.core.models import TranslationContext


def test_subtitle_cache_path_deterministic():
    """Cache path should be consistent for same inputs."""
    from subtrans.core.cache import get_subtitle_cache_path

    path1 = get_subtitle_cache_path(Path("/test/movie.mkv"), 0)
    path2 = get_subtitle_cache_path(Path("/test/movie.mkv"), 0)
    assert path1 == path2
    assert path1.name.endswith(".srt")
    assert path1.parent.name == "subtrans"


def test_subtitle_cache_path_different_tracks():
    """Different track IDs should produce different cache paths."""
    from subtrans.core.cache import get_subtitle_cache_path

    path1 = get_subtitle_cache_path(Path("/test/movie.mkv"), 0)
    path2 = get_subtitle_cache_path(Path("/test/movie.mkv"), 1)
    assert path1 != path2


def test_subtitle_cache_path_different_files():
    """Different files should produce different cache paths."""
    from subtrans.core.cache import get_subtitle_cache_path

    path1 = get_subtitle_cache_path(Path("/test/movie1.mkv"), 0)
    path2 = get_subtitle_cache_path(Path("/test/movie2.mkv"), 0)
    assert path1 != path2


def test_context_cache_path_sanitization():
    """Special characters should be removed from cache filenames."""
    from subtrans.core.cache import get_context_cache_path

    path = get_context_cache_path("Movie: The Sequel!", 2024)
    assert ":" not in path.name
    assert "!" not in path.name
    assert "Movie" in path.name
    assert "2024" in path.name
    assert path.name.endswith("_context.json")


def test_context_cache_path_spaces_to_underscores():
    """Spaces should be converted to underscores."""
    from subtrans.core.cache import get_context_cache_path

    path = get_context_cache_path("Test Movie Title", 2024)
    assert " " not in path.name
    assert "_" in path.name
    assert "Test" in path.name
    assert "Movie" in path.name


def test_save_and_load_context_roundtrip(tmp_path, monkeypatch):
    """Saved context should be loadable."""
    from subtrans.core.cache import save_context_cache, load_cached_context

    # Use tmp_path as cache dir
    monkeypatch.setattr("subtrans.core.cache.CACHE_DIR", tmp_path)

    context = TranslationContext(
        characters={"Alice": "Alice"},
        places={"London": "Lontoo"},
        terms={"cheers": "kippis"},
        genre="drama",
        tone="formal",
        formality="formal",
        style_notes="Period piece",
        raw_json={
            "characters": {"Alice": "Alice"},
            "places": {"London": "Lontoo"},
            "recurring_terms": {"cheers": "kippis"},
            "genre": "drama",
            "tone": "formal",
            "formality_recommendation": "formal",
            "style_notes": "Period piece"
        }
    )

    # Save
    result = save_context_cache(context, "Test Movie", 2024)
    assert result is True

    # Load
    loaded = load_cached_context("Test Movie", 2024)
    assert loaded is not None
    assert loaded.genre == "drama"
    assert loaded.characters == {"Alice": "Alice"}
    assert loaded.places == {"London": "Lontoo"}
    assert loaded.terms == {"cheers": "kippis"}
    assert loaded.tone == "formal"
    assert loaded.formality == "formal"
    assert loaded.style_notes == "Period piece"


def test_load_cached_context_missing(tmp_path, monkeypatch):
    """Loading non-existent context should return None."""
    from subtrans.core.cache import load_cached_context

    monkeypatch.setattr("subtrans.core.cache.CACHE_DIR", tmp_path)
    result = load_cached_context("Nonexistent Movie", 2024)
    assert result is None


def test_load_cached_context_invalid_json(tmp_path, monkeypatch):
    """Loading invalid JSON should return None."""
    from subtrans.core.cache import load_cached_context, get_context_cache_path

    monkeypatch.setattr("subtrans.core.cache.CACHE_DIR", tmp_path)

    # Create invalid JSON file
    cache_path = get_context_cache_path("Bad Movie", 2024)
    cache_path.write_text("invalid json{{{")

    result = load_cached_context("Bad Movie", 2024)
    assert result is None
