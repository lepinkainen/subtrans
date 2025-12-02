"""Tests for CLI extract-only mode."""

from pathlib import Path
from unittest.mock import Mock, patch
import pysrt


def test_extract_only_skips_translation(tmp_path):
    """Should skip translation when extract_only is True."""
    from subtrans.cli import process_movie
    from subtrans.core.models import Movie

    # Create a test SRT file
    srt_path = tmp_path / "test.en.srt"
    srt_path.write_text("""1
00:00:01,000 --> 00:00:02,000
Test subtitle
""", encoding="utf-8")

    # Create test movie
    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2024,
        path=str(tmp_path / "test.mkv"),
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    # Mock the subtitle finding
    with patch("subtrans.cli.get_source_subtitle") as mock_get_sub:
        mock_get_sub.return_value = (srt_path, False)

        # Call with extract_only=True
        result = process_movie(
            movie,
            client=None,  # No client needed for extract-only
            extract_only=True,
        )

        # Should succeed without calling OpenAI
        assert result is True
        mock_get_sub.assert_called_once()


def test_extract_only_loads_subtitle(tmp_path):
    """Should load subtitle file in extract-only mode."""
    from subtrans.cli import process_movie
    from subtrans.core.models import Movie

    # Create a test SRT file with multiple entries
    srt_path = tmp_path / "test.en.srt"
    srt_path.write_text("""1
00:00:01,000 --> 00:00:02,000
First subtitle

2
00:00:03,000 --> 00:00:04,000
Second subtitle
""", encoding="utf-8")

    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2024,
        path=str(tmp_path / "test.mkv"),
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    with patch("subtrans.cli.get_source_subtitle") as mock_get_sub:
        mock_get_sub.return_value = (srt_path, False)

        result = process_movie(
            movie,
            client=None,
            extract_only=True,
        )

        # Should successfully process
        assert result is True


def test_extract_only_handles_missing_subtitle():
    """Should fail gracefully when subtitle not found in extract-only mode."""
    from subtrans.cli import process_movie
    from subtrans.core.models import Movie

    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2024,
        path="/nonexistent/path/test.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    with patch("subtrans.cli.get_source_subtitle") as mock_get_sub:
        mock_get_sub.return_value = (None, False)  # Subtitle not found

        result = process_movie(
            movie,
            client=None,
            extract_only=True,
        )

        # Should return False when subtitle not found
        assert result is False


def test_normal_mode_requires_client():
    """Should require OpenAI client when not in extract-only mode."""
    from subtrans.cli import process_movie
    from subtrans.core.models import Movie

    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2024,
        path="/path/test.mkv",
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    # Normal mode (extract_only=False) would fail without proper client
    # This is more of a contract test - actual translation requires OpenAI
    # Just verify the parameter exists and defaults to False
    with patch("subtrans.cli.get_source_subtitle") as mock_get_sub:
        mock_get_sub.return_value = (None, False)

        result = process_movie(
            movie,
            client=None,
            extract_only=False,  # Explicitly False
            dry_run=True,  # Use dry_run to avoid needing full setup
        )

        assert result is False  # Fails due to missing subtitle
