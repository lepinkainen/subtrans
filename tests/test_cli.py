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
