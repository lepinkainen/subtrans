"""Tests for core.models module."""


def test_movie_dataclass():
    """Movie should be a valid dataclass."""
    from subtrans.core.models import Movie

    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2024,
        path="/path/to/movie.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=["en"]
    )
    assert movie.title == "Test Movie"
    assert movie.year == 2024
    assert movie.radarr_id == 1
    assert movie.path == "/path/to/movie.mkv"
    assert "fi" in movie.missing_subtitles
    assert "en" in movie.existing_subtitles


def test_subtitle_track_dataclass():
    """SubtitleTrack should be a valid dataclass."""
    from subtrans.core.models import SubtitleTrack

    track = SubtitleTrack(
        track_id=2,
        language="eng",
        name="English",
        codec="SubRip/SRT"
    )
    assert track.track_id == 2
    assert track.language == "eng"
    assert track.name == "English"
    assert track.codec == "SubRip/SRT"


def test_config_dataclass():
    """Config should be a valid dataclass."""
    from subtrans.core.models import Config

    config = Config(
        bazarr_url="http://test:6767",
        bazarr_api_key="test_key",
        openai_model="gpt-4",
        batch_size=50,
        path_mappings=[("/volume1", "/mnt")],
        skip_analysis=False,
        save_context=True,
        dry_run=False
    )
    assert config.bazarr_url == "http://test:6767"
    assert config.bazarr_api_key == "test_key"
    assert config.openai_model == "gpt-4"
    assert config.batch_size == 50
    assert config.path_mappings == [("/volume1", "/mnt")]
    assert config.skip_analysis is False
    assert config.save_context is True
    assert config.dry_run is False


def test_translation_context_dataclass():
    """TranslationContext should have all required fields."""
    from subtrans.core.models import TranslationContext

    context = TranslationContext(
        characters={"John": "John"},
        places={"New York": "New York"},
        terms={"hello": "moi"},
        genre="action",
        tone="serious",
        formality="informal",
        style_notes="Modern slang",
        raw_json={"test": "data"}
    )
    assert context.genre == "action"
    assert context.tone == "serious"
    assert context.formality == "informal"
    assert context.characters == {"John": "John"}
    assert context.places == {"New York": "New York"}
    assert context.terms == {"hello": "moi"}
    assert context.style_notes == "Modern slang"
    assert context.raw_json == {"test": "data"}
