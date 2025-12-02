"""Tests for processing.output module."""

from pathlib import Path
from unittest.mock import Mock

import pysrt


def test_save_finnish_subtitle_simple_filename(tmp_path):
    """Should correctly name output file for simple filename."""
    from subtrans.processing.output import save_finnish_subtitle

    # Create a dummy MKV file
    mkv = tmp_path / "movie.mkv"
    mkv.touch()

    # Create mock subtitle file
    subs = pysrt.SubRipFile()
    sub = pysrt.SubRipItem()
    sub.index = 1
    sub.start.seconds = 0
    sub.end.seconds = 1
    sub.text = "Test"
    subs.append(sub)

    # Save subtitle
    result = save_finnish_subtitle(subs, str(tmp_path), mkv_path=mkv)

    # Check output path
    assert result == tmp_path / "movie.fi.srt"
    assert result.exists()


def test_save_finnish_subtitle_multiple_dots(tmp_path):
    """Should correctly name output file for filename with multiple dots."""
    from subtrans.processing.output import save_finnish_subtitle

    # Create a dummy MKV file with multiple dots
    mkv = tmp_path / "Movie [1080p][x264].mkv"
    mkv.touch()

    # Create mock subtitle file
    subs = pysrt.SubRipFile()
    sub = pysrt.SubRipItem()
    sub.index = 1
    sub.start.seconds = 0
    sub.end.seconds = 1
    sub.text = "Test"
    subs.append(sub)

    # Save subtitle
    result = save_finnish_subtitle(subs, str(tmp_path), mkv_path=mkv)

    # Check output path preserves all parts before extension
    assert result == tmp_path / "Movie [1080p][x264].fi.srt"
    assert result.exists()


def test_save_finnish_subtitle_complex_real_world(tmp_path):
    """Should correctly name output file for complex real-world filename."""
    from subtrans.processing.output import save_finnish_subtitle

    # Create a dummy MKV file with complex real-world naming
    mkv = tmp_path / "Christmas Island (2023) {imdb-tt29378386} [WEBDL-1080p][EAC3 5.1][x264].mkv"
    mkv.touch()

    # Create mock subtitle file
    subs = pysrt.SubRipFile()
    sub = pysrt.SubRipItem()
    sub.index = 1
    sub.start.seconds = 0
    sub.end.seconds = 1
    sub.text = "Test"
    subs.append(sub)

    # Save subtitle
    result = save_finnish_subtitle(subs, str(tmp_path), mkv_path=mkv)

    # Check output path preserves entire filename structure
    expected = tmp_path / "Christmas Island (2023) {imdb-tt29378386} [WEBDL-1080p][EAC3 5.1][x264].fi.srt"
    assert result == expected
    assert result.exists()


def test_save_finnish_subtitle_with_directory_path(tmp_path):
    """Should correctly name output file when movie_path is a file."""
    from subtrans.processing.output import save_finnish_subtitle

    # Create a subdirectory
    movie_dir = tmp_path / "movies"
    movie_dir.mkdir()

    # Create a movie file
    movie_file = movie_dir / "movie.mkv"
    movie_file.touch()

    # Create mock subtitle file
    subs = pysrt.SubRipFile()
    sub = pysrt.SubRipItem()
    sub.index = 1
    sub.start.seconds = 0
    sub.end.seconds = 1
    sub.text = "Test"
    subs.append(sub)

    # Save subtitle without mkv_path (use movie_path as fallback)
    result = save_finnish_subtitle(subs, str(movie_file))

    # Check output path
    assert result == movie_dir / "movie.fi.srt"
    assert result.exists()


def test_save_finnish_subtitle_find_video_in_directory(tmp_path):
    """Should find video file in directory and use it for naming."""
    from subtrans.processing.output import save_finnish_subtitle

    # Create video files in directory
    (tmp_path / "movie.mkv").touch()
    (tmp_path / "sample.mp4").touch()

    # Create mock subtitle file
    subs = pysrt.SubRipFile()
    sub = pysrt.SubRipItem()
    sub.index = 1
    sub.start.seconds = 0
    sub.end.seconds = 1
    sub.text = "Test"
    subs.append(sub)

    # Save subtitle (movie_path is directory, no mkv_path)
    result = save_finnish_subtitle(subs, str(tmp_path))

    # Should use first found MKV
    assert result == tmp_path / "movie.fi.srt"
    assert result.exists()


def test_save_finnish_subtitle_fallback_to_cache_on_permission_error(tmp_path, monkeypatch):
    """Should fallback to cache directory when write fails."""
    from subtrans.processing.output import save_finnish_subtitle
    from subtrans.core.utils import CACHE_DIR

    # Create a dummy MKV file
    mkv = tmp_path / "movie.mkv"
    mkv.touch()

    # Create mock subtitle file
    subs = pysrt.SubRipFile()
    sub = pysrt.SubRipItem()
    sub.index = 1
    sub.start.seconds = 0
    sub.end.seconds = 1
    sub.text = "Test"
    subs.append(sub)

    # Mock the save method to raise PermissionError on first call
    original_save = subs.save
    call_count = {"count": 0}

    def mock_save(path, encoding="utf-8"):
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise PermissionError("Cannot write to NAS")
        else:
            # Actually save to the fallback location
            original_save(path, encoding=encoding)

    monkeypatch.setattr(subs, "save", mock_save)

    # Save subtitle
    result = save_finnish_subtitle(subs, str(tmp_path), mkv_path=mkv, movie_title="Test Movie", movie_year=2023)

    # Should fallback to cache directory
    assert result == CACHE_DIR / "Test_Movie_2023.fi.srt"
    assert result.exists()
