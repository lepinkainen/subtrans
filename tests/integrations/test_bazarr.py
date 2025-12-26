"""Tests for integrations.bazarr module."""


def test_get_wanted_movies_includes_all_missing_target(monkeypatch):
    """Movies missing target subtitles should be included regardless of source."""
    from subtrans.integrations.bazarr import get_wanted_movies

    mock_data = {
        "data": [
            {
                "title": "Movie With English",
                "year": 2020,
                "radarrId": 1,
                "missing_subtitles": [{"code2": "fi"}],
                "subtitles": [{"code2": "en", "code3": "eng"}],
            },
            {
                "title": "Movie Without English",
                "year": 2021,
                "radarrId": 2,
                "missing_subtitles": [{"code2": "fi"}],
                "subtitles": [{"code2": "fr"}],
            },
        ]
    }

    class MockResponse:
        def json(self):
            return mock_data

        def raise_for_status(self):
            pass

    class MockClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return MockResponse()

    monkeypatch.setattr("httpx.Client", lambda **kwargs: MockClient())

    result = get_wanted_movies("http://test", "key", source_lang="en", target_lang="fi")

    # Both movies should be included - no longer filtered by source language
    assert len(result) == 2
    titles = [movie.title for movie in result]
    assert "Movie With English" in titles
    assert "Movie Without English" in titles


def test_get_wanted_movies_includes_all_without_source_logging(monkeypatch, capsys):
    """Should include movies even without source subtitles."""
    from subtrans.integrations.bazarr import get_wanted_movies

    mock_data = {
        "data": [
            {
                "title": "Test Movie",
                "year": 2020,
                "radarrId": 1,
                "missing_subtitles": [{"code2": "fi"}],
                "subtitles": [{"code2": "fr"}, {"code2": "de"}],
            }
        ]
    }

    class MockResponse:
        def json(self):
            return mock_data

        def raise_for_status(self):
            pass

    class MockClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return MockResponse()

    monkeypatch.setattr("httpx.Client", lambda **kwargs: MockClient())

    result = get_wanted_movies("http://test", "key", source_lang="en", target_lang="fi")

    # Movie should be included - no longer filtered by source language
    assert len(result) == 1
    assert result[0].title == "Test Movie"


def test_get_wanted_movies_respects_source_lang_parameter(monkeypatch):
    """Should use custom source_lang parameter."""
    from subtrans.integrations.bazarr import get_wanted_movies

    mock_data = {
        "data": [
            {
                "title": "Spanish Movie",
                "year": 2020,
                "radarrId": 1,
                "missing_subtitles": [{"code2": "fi"}],
                "subtitles": [{"code2": "es"}],
            }
        ]
    }

    class MockResponse:
        def json(self):
            return mock_data

        def raise_for_status(self):
            pass

    class MockClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return MockResponse()

    monkeypatch.setattr("httpx.Client", lambda **kwargs: MockClient())

    result = get_wanted_movies("http://test", "key", source_lang="es", target_lang="fi")

    assert len(result) == 1
    assert result[0].title == "Spanish Movie"


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

    mappings = [("/volume1/movies", "/mnt/movies"), ("/volume2/tv", "/mnt/tv")]
    result = apply_path_mapping("/volume2/tv/Show/s01e01.mkv", mappings)
    assert result == "/mnt/tv/Show/s01e01.mkv"


def test_apply_path_mapping_first_match_wins():
    """Should use first matching mapping."""
    from subtrans.integrations.bazarr import apply_path_mapping

    mappings = [("/volume1", "/mnt1"), ("/volume1/movies", "/mnt/movies")]
    result = apply_path_mapping("/volume1/movies/test.mkv", mappings)
    assert result == "/mnt1/movies/test.mkv"


def test_apply_path_mapping_empty_list():
    """Empty mapping list should return original path."""
    from subtrans.integrations.bazarr import apply_path_mapping

    result = apply_path_mapping("/test/path.mkv", [])
    assert result == "/test/path.mkv"


def test_get_wanted_episodes_includes_all_missing_target(monkeypatch):
    """Episodes missing target subtitles should be included regardless of source."""
    from subtrans.integrations.bazarr import get_wanted_episodes

    # Note: Bazarr's wanted API returns episode_number as "SxE" format string (e.g., "1x1")
    mock_data = {
        "data": [
            {
                "seriesTitle": "Show Name",
                "episode_number": "1x1",  # Bazarr format: SxE
                "episodeTitle": "Pilot",
                "sonarrEpisodeId": 101,
                "sonarrSeriesId": 10,
                "missing_subtitles": [{"code2": "fi"}],
                "subtitles": [{"code2": "en", "code3": "eng"}],
            },
            {
                "seriesTitle": "Another Show",
                "episode_number": "2x5",  # Bazarr format: SxE
                "episodeTitle": "Episode Five",
                "sonarrEpisodeId": 205,
                "sonarrSeriesId": 20,
                "missing_subtitles": [{"code2": "fi"}],
                "subtitles": [{"code2": "fr"}],
            },
        ]
    }

    class MockResponse:
        def json(self):
            return mock_data

        def raise_for_status(self):
            pass

    class MockClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return MockResponse()

    monkeypatch.setattr("httpx.Client", lambda **kwargs: MockClient())

    result = get_wanted_episodes(
        "http://test", "key", source_lang="en", target_lang="fi"
    )

    # Both episodes should be included
    assert len(result) == 2
    assert result[0].series_name == "Show Name"
    assert result[0].season_number == 1
    assert result[0].episode_number == 1
    assert result[0].episode_title == "Pilot"
    assert result[0].sonarr_id == 101
    assert result[0].sonarr_series_id == 10
    assert result[1].series_name == "Another Show"
    assert result[1].season_number == 2
    assert result[1].episode_number == 5
    assert result[1].sonarr_series_id == 20


def test_populate_episode_path_success(monkeypatch):
    """Should populate episode path from API."""
    from subtrans.core.models import Episode
    from subtrans.integrations.bazarr import populate_episode_path

    episode = Episode(
        sonarr_id=101,
        series_name="Test Show",
        season_number=0,  # Will be updated from API
        episode_number=0,  # Will be updated from API
        episode_title="Pilot",
        path="",
        missing_subtitles=["fi"],
        existing_subtitles=[],
        series_year=0,
        sonarr_series_id=10,  # Required for API lookup
    )

    # Mock data matching actual Bazarr /api/episodes response structure
    mock_data = {
        "data": [
            {
                "sonarrEpisodeId": 101,
                "path": "/tv/Test.Show/Season.01/S01E01.mkv",
                "season": 1,
                "episode": 1,
            }
        ]
    }

    class MockResponse:
        def json(self):
            return mock_data

        def raise_for_status(self):
            pass

    class MockClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return MockResponse()

    monkeypatch.setattr("httpx.Client", lambda **kwargs: MockClient())

    result = populate_episode_path(episode, "http://test", "key")

    assert result is True
    assert episode.path == "/tv/Test.Show/Season.01/S01E01.mkv"
    # Season/episode numbers should be updated from API response
    assert episode.season_number == 1
    assert episode.episode_number == 1


def test_populate_episode_path_not_found(monkeypatch, capsys):
    """Should handle episode not found gracefully."""
    from subtrans.core.models import Episode
    from subtrans.integrations.bazarr import populate_episode_path

    episode = Episode(
        sonarr_id=999,
        series_name="Missing Show",
        season_number=1,
        episode_number=1,
        episode_title="Missing",
        path="",
        missing_subtitles=["fi"],
        existing_subtitles=[],
        series_year=0,
        sonarr_series_id=10,  # Required for API lookup
    )

    mock_data = {"data": []}

    class MockResponse:
        def json(self):
            return mock_data

        def raise_for_status(self):
            pass

    class MockClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return MockResponse()

    monkeypatch.setattr("httpx.Client", lambda **kwargs: MockClient())

    result = populate_episode_path(episode, "http://test", "key")

    # Changed: Now returns True even when path isn't found (not a fatal error)
    assert result is True
    assert episode.path == ""
