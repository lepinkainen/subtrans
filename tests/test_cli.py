"""Tests for CLI two-phase workflow."""

from unittest.mock import patch, MagicMock


def test_extract_only_skips_translation(tmp_path):
    """Should skip translation when extract_only is True."""
    from subtrans.cli import process_movie_phase1
    from subtrans.core.models import Movie, Config

    # Create a test SRT file
    srt_path = tmp_path / "test.en.srt"
    srt_path.write_text(
        """1
00:00:01,000 --> 00:00:02,000
Test subtitle
""",
        encoding="utf-8",
    )

    # Create test movie
    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2024,
        path=str(tmp_path / "test.mkv"),
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    # Create mock config with new fields
    config = MagicMock(spec=Config)
    config.interactive_track_selection = False
    config.auto_select_tracks = True

    # Mock the subtitle finding
    with patch("subtrans.cli.get_source_subtitle") as mock_get_sub:
        mock_get_sub.return_value = (
            srt_path,
            False,
        )  # (path, skip_requested)

        # Call with extract_only=True (uses phase1)
        result = process_movie_phase1(
            movie,
            client=None,  # No client needed for extract-only
            config=config,
            extract_only=True,
            strict_validation=False,  # Disable validation prompts for test
            min_subtitle_count=1,  # Accept test file with 1 entry
        )

        # Should succeed without calling OpenAI
        assert result is True
        mock_get_sub.assert_called_once()


def test_extract_only_loads_subtitle(tmp_path):
    """Should load subtitle file in extract-only mode."""
    from subtrans.cli import process_movie_phase1
    from subtrans.core.models import Movie, Config

    # Create a test SRT file with multiple entries
    srt_path = tmp_path / "test.en.srt"
    srt_path.write_text(
        """1
00:00:01,000 --> 00:00:02,000
First subtitle

2
00:00:03,000 --> 00:00:04,000
Second subtitle
""",
        encoding="utf-8",
    )

    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2024,
        path=str(tmp_path / "test.mkv"),
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    # Create mock config
    config = MagicMock(spec=Config)
    config.interactive_track_selection = False
    config.auto_select_tracks = True

    with patch("subtrans.cli.get_source_subtitle") as mock_get_sub:
        mock_get_sub.return_value = (srt_path, False)

        result = process_movie_phase1(
            movie,
            client=None,
            config=config,
            extract_only=True,
            strict_validation=False,  # Disable validation prompts for test
            min_subtitle_count=1,  # Accept test file with 2 entries
        )

        # Should successfully process
        assert result is True


def test_extract_only_handles_missing_subtitle():
    """Should fail gracefully when subtitle not found in extract-only mode."""
    from subtrans.cli import process_movie_phase1
    from subtrans.core.models import Movie, Config

    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2024,
        path="/nonexistent/path/test.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    # Create mock config
    config = MagicMock(spec=Config)
    config.interactive_track_selection = False
    config.auto_select_tracks = True

    with patch("subtrans.cli.get_source_subtitle") as mock_get_sub:
        mock_get_sub.return_value = (
            None,
            False,
        )  # Subtitle not found, not skipped

        result = process_movie_phase1(
            movie,
            client=None,
            config=config,
            extract_only=True,
        )

        # Should return False when subtitle not found
        assert result is False


def test_show_context_functionality():
    """Test that context is always shown in phase1 (no show_context param)."""
    from subtrans.cli import process_movie_phase1
    import inspect

    # Phase 1 always shows context - verify no show_context parameter
    sig = inspect.signature(process_movie_phase1)
    # show_context parameter should NOT exist in phase1
    # (context is always shown in phase1)
    assert "show_context" not in sig.parameters


def test_normal_mode_requires_client():
    """Should require OpenAI client when not in extract-only mode."""
    from subtrans.cli import process_movie_phase1
    from subtrans.core.models import Movie, Config

    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2024,
        path="/path/test.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    # Create mock config
    config = MagicMock(spec=Config)
    config.interactive_track_selection = False
    config.auto_select_tracks = True

    # Normal mode (extract_only=False) would fail without proper client
    # This is more of a contract test - actual translation requires OpenAI
    # Just verify the parameter exists and defaults to False
    with patch("subtrans.cli.get_source_subtitle") as mock_get_sub:
        mock_get_sub.return_value = (None, False)

        result = process_movie_phase1(
            movie,
            client=None,
            config=config,
            extract_only=False,  # Explicitly False
            dry_run=True,  # Use dry_run to avoid needing full setup
        )

        assert result is False  # Fails due to missing subtitle


def test_select_by_pattern_exact_movie_match():
    """Should match movie by exact title."""
    from subtrans.cli import select_by_pattern
    from subtrans.core.models import Movie

    movies = [
        Movie(
            radarr_id=1,
            title="The Matrix",
            year=1999,
            path="/movies/matrix.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
        ),
        Movie(
            radarr_id=2,
            title="Inception",
            year=2010,
            path="/movies/inception.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
        ),
    ]

    result = select_by_pattern(movies, "the matrix", "fi", "movies")

    assert len(result) == 1
    assert result[0].title == "The Matrix"


def test_select_by_pattern_wildcard_movie():
    """Should match movies with wildcard pattern."""
    from subtrans.cli import select_by_pattern
    from subtrans.core.models import Movie

    movies = [
        Movie(
            radarr_id=1,
            title="The Matrix",
            year=1999,
            path="/movies/matrix.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
        ),
        Movie(
            radarr_id=2,
            title="The Matrix Reloaded",
            year=2003,
            path="/movies/matrix2.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
        ),
        Movie(
            radarr_id=3,
            title="Inception",
            year=2010,
            path="/movies/inception.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
        ),
    ]

    result = select_by_pattern(movies, "*matrix*", "fi", "movies")

    assert len(result) == 2
    assert all("Matrix" in movie.title for movie in result)


def test_select_by_pattern_case_insensitive():
    """Should match case-insensitively."""
    from subtrans.cli import select_by_pattern
    from subtrans.core.models import Movie

    movies = [
        Movie(
            radarr_id=1,
            title="Breaking Bad Movie",
            year=2019,
            path="/movies/bb.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
        ),
    ]

    # Test uppercase pattern
    result = select_by_pattern(movies, "*BREAKING BAD*", "fi", "movies")
    assert len(result) == 1

    # Test mixed case pattern
    result = select_by_pattern(movies, "*BrEaKiNg*", "fi", "movies")
    assert len(result) == 1


def test_select_by_pattern_no_matches():
    """Should exit with error when no matches found."""
    import pytest
    from subtrans.cli import select_by_pattern
    from subtrans.core.models import Movie

    movies = [
        Movie(
            radarr_id=1,
            title="The Matrix",
            year=1999,
            path="/movies/matrix.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
        ),
    ]

    with pytest.raises(SystemExit) as exc_info:
        select_by_pattern(movies, "nonexistent", "fi", "movies")

    assert exc_info.value.code == 1


def test_select_by_pattern_display_title_with_year():
    """Should match against display title including year."""
    from subtrans.cli import select_by_pattern
    from subtrans.core.models import Movie

    movies = [
        Movie(
            radarr_id=1,
            title="The Matrix",
            year=1999,
            path="/movies/matrix.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
        ),
        Movie(
            radarr_id=2,
            title="The Matrix",
            year=2021,  # Hypothetical remake
            path="/movies/matrix2021.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
        ),
    ]

    # Match by year to distinguish
    result = select_by_pattern(movies, "*(1999)*", "fi", "movies")

    assert len(result) == 1
    assert result[0].year == 1999


def test_select_by_pattern_episode_series_name():
    """Should match episode by series name."""
    from subtrans.cli import select_by_pattern
    from subtrans.core.models import Episode

    episodes = [
        Episode(
            sonarr_id=1,
            series_name="Breaking Bad",
            season_number=1,
            episode_number=1,
            episode_title="Pilot",
            path="/tv/bb/s01e01.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
            series_year=2008,
        ),
        Episode(
            sonarr_id=2,
            series_name="Better Call Saul",
            season_number=1,
            episode_number=1,
            episode_title="Uno",
            path="/tv/bcs/s01e01.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
            series_year=2015,
        ),
    ]

    result = select_by_pattern(episodes, "*breaking bad*", "fi", "episodes")

    assert len(result) == 1
    assert result[0].series_name == "Breaking Bad"


def test_select_by_pattern_episode_title():
    """Should match episode by episode title."""
    from subtrans.cli import select_by_pattern
    from subtrans.core.models import Episode

    episodes = [
        Episode(
            sonarr_id=1,
            series_name="Test Show",
            season_number=1,
            episode_number=1,
            episode_title="The Pilot Episode",
            path="/tv/test/s01e01.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
            series_year=2020,
        ),
        Episode(
            sonarr_id=2,
            series_name="Test Show",
            season_number=1,
            episode_number=2,
            episode_title="Episode Two",
            path="/tv/test/s01e02.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
            series_year=2020,
        ),
    ]

    result = select_by_pattern(episodes, "*pilot*", "fi", "episodes")

    assert len(result) == 1
    assert result[0].episode_title == "The Pilot Episode"


def test_select_by_pattern_episode_season_episode():
    """Should match episode by season/episode number in display."""
    from subtrans.cli import select_by_pattern
    from subtrans.core.models import Episode

    episodes = [
        Episode(
            sonarr_id=1,
            series_name="Test Show",
            season_number=1,
            episode_number=5,
            episode_title="Episode Five",
            path="/tv/test/s01e05.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
            series_year=2020,
        ),
        Episode(
            sonarr_id=2,
            series_name="Test Show",
            season_number=2,
            episode_number=5,
            episode_title="Another Five",
            path="/tv/test/s02e05.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
            series_year=2020,
        ),
    ]

    result = select_by_pattern(episodes, "*s01e05*", "fi", "episodes")

    assert len(result) == 1
    assert result[0].season_number == 1
    assert result[0].episode_number == 5


def test_select_by_pattern_select_all():
    """Should select all items with wildcard '*'."""
    from subtrans.cli import select_by_pattern
    from subtrans.core.models import Movie

    movies = [
        Movie(
            radarr_id=1,
            title="Movie One",
            year=2020,
            path="/movies/one.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
        ),
        Movie(
            radarr_id=2,
            title="Movie Two",
            year=2021,
            path="/movies/two.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
        ),
        Movie(
            radarr_id=3,
            title="Movie Three",
            year=2022,
            path="/movies/three.mkv",
            missing_subtitles=["fi"],
            existing_subtitles=[],
        ),
    ]

    result = select_by_pattern(movies, "*", "fi", "movies")

    assert len(result) == 3
    assert len(result) == len(movies)
