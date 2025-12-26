"""Tests for processing.output module."""

import sys
from pathlib import Path

# Add the project root to path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from subtrans.core.models import Movie, Episode


def test_save_translated_subtitle_simple_filename(tmp_path):
    """Should correctly name output file for simple filename."""
    from subtrans.processing.output import save_translated_subtitle
    import pysrt

    # Create a dummy MKV file
    mkv = tmp_path / "movie.mkv"
    mkv.touch()

    # Create mock movie
    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2023,
        path=str(tmp_path),
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    # Create mock subtitle file
    subs = pysrt.SubRipFile()
    sub = pysrt.SubRipItem()
    sub.index = 1
    sub.start.seconds = 0
    sub.end.seconds = 1
    sub.text = "Test"
    subs.append(sub)

    # Save subtitle
    result = save_translated_subtitle(subs, movie, mkv_path=mkv)

    # Check output path
    assert result == tmp_path / "movie.fi.srt"
    assert result.exists()


def test_save_translated_subtitle_multiple_dots(tmp_path):
    """Should correctly name output file for filename with multiple dots."""
    from subtrans.processing.output import save_translated_subtitle
    import pysrt

    # Create a dummy MKV file with multiple dots
    mkv = tmp_path / "Movie [1080p][x264].mkv"
    mkv.touch()

    # Create mock movie
    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2023,
        path=str(tmp_path),
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    # Create mock subtitle file
    subs = pysrt.SubRipFile()
    sub = pysrt.SubRipItem()
    sub.index = 1
    sub.start.seconds = 0
    sub.end.seconds = 1
    sub.text = "Test"
    subs.append(sub)

    # Save subtitle
    result = save_translated_subtitle(subs, movie, mkv_path=mkv)

    # Check output path preserves all parts before extension
    assert result == tmp_path / "Movie [1080p][x264].fi.srt"
    assert result.exists()


def test_save_translated_subtitle_complex_real_world(tmp_path):
    """Should correctly name output file for complex real-world filename."""
    from subtrans.processing.output import save_translated_subtitle
    import pysrt

    # Create a dummy MKV file with complex real-world naming
    mkv = (
        tmp_path
        / "Christmas Island (2023) {imdb-tt29378386} [WEBDL-1080p][EAC3 5.1][x264].mkv"
    )
    mkv.touch()

    # Create mock movie
    movie = Movie(
        radarr_id=1,
        title="Christmas Island",
        year=2023,
        path=str(tmp_path),
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    # Create mock subtitle file
    subs = pysrt.SubRipFile()
    sub = pysrt.SubRipItem()
    sub.index = 1
    sub.start.seconds = 0
    sub.end.seconds = 1
    sub.text = "Test"
    subs.append(sub)

    # Save subtitle
    result = save_translated_subtitle(subs, movie, mkv_path=mkv)

    # Check output path preserves entire filename structure
    expected = (
        tmp_path
        / "Christmas Island (2023) {imdb-tt29378386} [WEBDL-1080p][EAC3 5.1][x264].fi.srt"
    )
    assert result == expected
    assert result.exists()


def test_save_translated_subtitle_with_directory_path(tmp_path):
    """Should correctly name output file when movie_path is a file."""
    from subtrans.processing.output import save_translated_subtitle
    import pysrt

    # Create a subdirectory
    movie_dir = tmp_path / "movies"
    movie_dir.mkdir()

    # Create a movie file
    movie_file = movie_dir / "movie.mkv"
    movie_file.touch()

    # Create mock movie
    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2023,
        path=str(movie_file),
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    # Create mock subtitle file
    subs = pysrt.SubRipFile()
    sub = pysrt.SubRipItem()
    sub.index = 1
    sub.start.seconds = 0
    sub.end.seconds = 1
    sub.text = "Test"
    subs.append(sub)

    # Save subtitle without mkv_path (use movie_path as fallback)
    result = save_translated_subtitle(subs, movie)

    # Check output path
    assert result == movie_dir / "movie.fi.srt"
    assert result.exists()


def test_save_translated_subtitle_find_video_in_directory(tmp_path):
    """Should find video file in directory and use it for naming."""
    from subtrans.processing.output import save_translated_subtitle
    import pysrt

    # Create video files in directory
    (tmp_path / "movie.mkv").touch()
    (tmp_path / "sample.mp4").touch()

    # Create mock movie
    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2023,
        path=str(tmp_path),
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

    # Create mock subtitle file
    subs = pysrt.SubRipFile()
    sub = pysrt.SubRipItem()
    sub.index = 1
    sub.start.seconds = 0
    sub.end.seconds = 1
    sub.text = "Test"
    subs.append(sub)

    # Save subtitle (movie_path is directory, no mkv_path)
    result = save_translated_subtitle(subs, movie)

    # Should use first found MKV
    assert result == tmp_path / "movie.fi.srt"
    assert result.exists()


def test_save_translated_subtitle_fallback_to_cache_on_permission_error(
    tmp_path, monkeypatch
):
    """Should fallback to cache directory when write fails."""
    from subtrans.processing.output import save_translated_subtitle
    from subtrans.core.utils import CACHE_DIR
    import pysrt

    # Create a dummy MKV file
    mkv = tmp_path / "movie.mkv"
    mkv.touch()

    # Create mock movie
    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2023,
        path=str(tmp_path),
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )

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
    result = save_translated_subtitle(subs, movie, mkv_path=mkv)

    # Should fallback to cache directory
    assert result == CACHE_DIR / "Test_Movie_2023.fi.srt"
    assert result.exists()


# Episode Tests


def test_save_translated_subtitle_episode_simple(tmp_path):
    """Should correctly name output file for episode with simple filename."""
    from subtrans.processing.output import save_translated_subtitle
    import pysrt

    # Create a dummy MKV file
    mkv = tmp_path / "Breaking.Bad.S01E01.mkv"
    mkv.touch()

    # Create mock episode
    episode = Episode(
        sonarr_id=1,
        series_name="Breaking Bad",
        season_number=1,
        episode_number=1,
        episode_title="Pilot",
        path=str(tmp_path),
        missing_subtitles=["fi"],
        existing_subtitles=[],
        series_year=2008,
    )

    # Create mock subtitle file
    subs = pysrt.SubRipFile()
    sub = pysrt.SubRipItem()
    sub.index = 1
    sub.start.seconds = 0
    sub.end.seconds = 1
    sub.text = "Test"
    subs.append(sub)

    # Save subtitle
    result = save_translated_subtitle(subs, episode, mkv_path=mkv)

    # Check output path uses episode naming format
    assert result == tmp_path / "Breaking.Bad.S01E01.fi.srt"
    assert result.exists()


def test_save_translated_subtitle_episode_with_special_chars(tmp_path):
    """Should sanitize series name with special characters."""
    from subtrans.processing.output import save_translated_subtitle
    import pysrt

    # Create a dummy MKV file
    mkv = tmp_path / "episode.mkv"
    mkv.touch()

    # Create mock episode with special characters in series name
    episode = Episode(
        sonarr_id=1,
        series_name="It's Always Sunny in Philadelphia",
        season_number=2,
        episode_number=5,
        episode_title="Hundred Dollar Baby",
        path=str(tmp_path),
        missing_subtitles=["fi"],
        existing_subtitles=[],
        series_year=2005,
    )

    # Create mock subtitle file
    subs = pysrt.SubRipFile()
    sub = pysrt.SubRipItem()
    sub.index = 1
    sub.start.seconds = 0
    sub.end.seconds = 1
    sub.text = "Test"
    subs.append(sub)

    # Save subtitle
    result = save_translated_subtitle(subs, episode, mkv_path=mkv)

    # Check output path sanitizes series name (removes apostrophe)
    assert result == tmp_path / "Its.Always.Sunny.in.Philadelphia.S02E05.fi.srt"
    assert result.exists()


def test_save_translated_subtitle_episode_fallback_to_cache(tmp_path, monkeypatch):
    """Should fallback to cache directory for episode when write fails."""
    from subtrans.processing.output import save_translated_subtitle
    from subtrans.core.utils import CACHE_DIR
    import pysrt

    # Create a dummy MKV file
    mkv = tmp_path / "episode.mkv"
    mkv.touch()

    # Create mock episode
    episode = Episode(
        sonarr_id=1,
        series_name="The Wire",
        season_number=1,
        episode_number=3,
        episode_title="The Buys",
        path=str(tmp_path),
        missing_subtitles=["fi"],
        existing_subtitles=[],
        series_year=2002,
    )

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
            original_save(path, encoding=encoding)

    monkeypatch.setattr(subs, "save", mock_save)

    # Save subtitle
    result = save_translated_subtitle(subs, episode, mkv_path=mkv)

    # Should fallback to cache directory with episode naming
    assert result == CACHE_DIR / "The_Wire_S01E03.fi.srt"
    assert result.exists()


def test_check_translation_exists_episode(tmp_path):
    """Should correctly check if episode translation exists."""
    from subtrans.processing.output import check_translation_exists

    # Create a dummy MKV file
    mkv = tmp_path / "episode.mkv"
    mkv.touch()

    # Create mock episode
    episode = Episode(
        sonarr_id=1,
        series_name="Game of Thrones",
        season_number=1,
        episode_number=1,
        episode_title="Winter Is Coming",
        path=str(mkv),
        missing_subtitles=["fi"],
        existing_subtitles=[],
        series_year=2011,
    )

    # Translation doesn't exist yet
    exists, path = check_translation_exists(episode)
    assert not exists
    assert path is None

    # Create the translation file
    translation_path = tmp_path / "Game.of.Thrones.S01E01.fi.srt"
    translation_path.touch()

    # Now it should be found
    exists, path = check_translation_exists(episode)
    assert exists
    assert path == translation_path


def test_check_translation_exists_episode_in_cache(tmp_path):
    """Should find episode translation in cache directory."""
    from subtrans.processing.output import check_translation_exists
    from subtrans.core.utils import CACHE_DIR

    # Create mock episode
    episode = Episode(
        sonarr_id=1,
        series_name="The Sopranos",
        season_number=3,
        episode_number=7,
        episode_title="Second Opinion",
        path=str(tmp_path / "nonexistent.mkv"),  # File doesn't exist
        missing_subtitles=["fi"],
        existing_subtitles=[],
        series_year=1999,
    )

    # Create translation in cache
    cache_path = CACHE_DIR / "The_Sopranos_S03E07.fi.srt"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.touch()

    # Should find it in cache
    exists, path = check_translation_exists(episode)
    assert exists
    assert path == cache_path
