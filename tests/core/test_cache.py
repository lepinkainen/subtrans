"""Tests for core.cache module."""

from pathlib import Path
from subtrans.core.models import TranslationContext, Movie, Episode


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

    movie = Movie(
        radarr_id=1,
        title="Movie: The Sequel!",
        year=2024,
        path="/test/movie.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    path = get_context_cache_path(movie)
    assert ":" not in path.name
    assert "!" not in path.name
    assert "Movie" in path.name
    assert "2024" in path.name
    assert path.name.endswith("_context.json")


def test_context_cache_path_spaces_to_underscores():
    """Spaces should be converted to underscores."""
    from subtrans.core.cache import get_context_cache_path

    movie = Movie(
        radarr_id=1,
        title="Test Movie Title",
        year=2024,
        path="/test/movie.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    path = get_context_cache_path(movie)
    assert " " not in path.name
    assert "_" in path.name
    assert "Test" in path.name
    assert "Movie" in path.name


def test_save_and_load_context_roundtrip(tmp_path, monkeypatch):
    """Saved context should be loadable."""
    from subtrans.core.cache import save_context_cache, load_cached_context

    # Use tmp_path as cache dir
    monkeypatch.setattr("subtrans.core.cache.CACHE_DIR", tmp_path)

    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2024,
        path="/test/movie.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    context = TranslationContext(
        characters={"Alice": "Alice"},
        places={"London": "Lontoo"},
        terms={"cheers": "kippis"},
        genre="drama",
        tone="formal",
        formality="formal",
        style_notes="Period piece",
        domains=["police_intelligence", "military"],
        domain_glossaries={
            "police_intelligence": {"MI5": "MI5 (Britannian salainen palvelu)"},
            "military": {"sergeant": "kersantti"},
        },
        raw_json={
            "characters": {"Alice": "Alice"},
            "places": {"London": "Lontoo"},
            "recurring_terms": {"cheers": "kippis"},
            "genre": "drama",
            "tone": "formal",
            "formality_recommendation": "formal",
            "style_notes": "Period piece",
            "domains": ["police_intelligence", "military"],
            "domain_glossaries": {
                "police_intelligence": {"MI5": "MI5 (Britannian salainen palvelu)"},
                "military": {"sergeant": "kersantti"},
            },
        },
    )

    # Save
    result = save_context_cache(context, movie)
    assert result is True

    # Load
    loaded = load_cached_context(movie)
    assert loaded is not None
    assert loaded.genre == "drama"
    assert loaded.characters == {"Alice": "Alice"}
    assert loaded.places == {"London": "Lontoo"}
    assert loaded.terms == {"cheers": "kippis"}
    assert loaded.tone == "formal"
    assert loaded.formality == "formal"
    assert loaded.style_notes == "Period piece"
    assert loaded.domains == ["police_intelligence", "military"]
    assert loaded.domain_glossaries == {
        "police_intelligence": {"MI5": "MI5 (Britannian salainen palvelu)"},
        "military": {"sergeant": "kersantti"},
    }


def test_load_cached_context_missing(tmp_path, monkeypatch):
    """Loading non-existent context should return None."""
    from subtrans.core.cache import load_cached_context

    monkeypatch.setattr("subtrans.core.cache.CACHE_DIR", tmp_path)

    movie = Movie(
        radarr_id=1,
        title="Nonexistent Movie",
        year=2024,
        path="/test/movie.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    result = load_cached_context(movie)
    assert result is None


def test_load_cached_context_invalid_json(tmp_path, monkeypatch):
    """Loading invalid JSON should return None."""
    from subtrans.core.cache import load_cached_context, get_context_cache_path

    monkeypatch.setattr("subtrans.core.cache.CACHE_DIR", tmp_path)

    movie = Movie(
        radarr_id=1,
        title="Bad Movie",
        year=2024,
        path="/test/movie.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    # Create invalid JSON file
    cache_path = get_context_cache_path(movie)
    cache_path.write_text("invalid json{{{")

    result = load_cached_context(movie)
    assert result is None


# Episode Tests


def test_context_cache_path_episode():
    """Episode cache path should include season and episode numbers."""
    from subtrans.core.cache import get_context_cache_path

    episode = Episode(
        sonarr_id=1,
        series_name="Breaking Bad",
        season_number=1,
        episode_number=5,
        episode_title="Gray Matter",
        path="/test/episode.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=[],
        series_year=2008,
    )

    path = get_context_cache_path(episode)
    assert "Breaking_Bad" in path.name
    assert "S01E05" in path.name
    assert "2008" in path.name
    assert path.name.endswith("_context.json")


def test_context_cache_path_episode_special_chars():
    """Episode cache path should sanitize series name."""
    from subtrans.core.cache import get_context_cache_path

    episode = Episode(
        sonarr_id=1,
        series_name="It's Always Sunny!",
        season_number=2,
        episode_number=10,
        episode_title="Test",
        path="/test/episode.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=[],
        series_year=2005,
    )

    path = get_context_cache_path(episode)
    assert "'" not in path.name
    assert "!" not in path.name
    assert "Its" in path.name
    assert "S02E10" in path.name


def test_save_and_load_context_episode_roundtrip(tmp_path, monkeypatch):
    """Saved episode context should be loadable."""
    from subtrans.core.cache import save_context_cache, load_cached_context

    monkeypatch.setattr("subtrans.core.cache.CACHE_DIR", tmp_path)

    episode = Episode(
        sonarr_id=1,
        series_name="The Wire",
        season_number=1,
        episode_number=1,
        episode_title="The Target",
        path="/test/episode.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=[],
        series_year=2002,
    )

    context = TranslationContext(
        characters={"McNulty": "McNulty"},
        places={"Baltimore": "Baltimore"},
        terms={"wire": "salakuuntelu"},
        genre="crime",
        tone="serious",
        formality="informal",
        style_notes="Police procedural",
        domains=[],
        domain_glossaries={},
        raw_json={
            "characters": {"McNulty": "McNulty"},
            "places": {"Baltimore": "Baltimore"},
            "recurring_terms": {"wire": "salakuuntelu"},
            "genre": "crime",
            "tone": "serious",
            "formality_recommendation": "informal",
            "style_notes": "Police procedural",
            "domains": [],
            "domain_glossaries": {},
        },
    )

    # Save
    result = save_context_cache(context, episode)
    assert result is True

    # Load
    loaded = load_cached_context(episode)
    assert loaded is not None
    assert loaded.genre == "crime"
    assert loaded.characters == {"McNulty": "McNulty"}
    assert loaded.places == {"Baltimore": "Baltimore"}
    assert loaded.terms == {"wire": "salakuuntelu"}


def test_episode_and_movie_cache_paths_different(tmp_path):
    """Episode and movie cache paths should be different even with similar names."""
    from subtrans.core.cache import get_context_cache_path

    movie = Movie(
        radarr_id=1,
        title="Test",
        year=2024,
        path="/test/movie.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    episode = Episode(
        sonarr_id=1,
        series_name="Test",
        season_number=1,
        episode_number=1,
        episode_title="Pilot",
        path="/test/episode.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=[],
        series_year=2024,
    )

    movie_path = get_context_cache_path(movie)
    episode_path = get_context_cache_path(episode)

    assert movie_path != episode_path
    assert "S01E01" in episode_path.name
    assert "S01E01" not in movie_path.name
