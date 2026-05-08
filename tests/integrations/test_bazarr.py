"""Tests for integrations.bazarr module."""


def _mock_httpx(monkeypatch, payloads_by_url=None, payload=None):
    """Install a fake httpx.Client returning the given JSON payload.

    ``payloads_by_url`` (optional) is a mapping of URL substring -> payload;
    ``payload`` (optional) is used when no per-url match is desired.
    """

    class MockResponse:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    class MockClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            url = args[0] if args else ""
            if payloads_by_url:
                for needle, data in payloads_by_url.items():
                    if needle in url:
                        return MockResponse(data)
            return MockResponse(payload)

    monkeypatch.setattr("httpx.Client", lambda **kwargs: MockClient())


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


def test_get_wanted_movies_year_populated_after_selection(monkeypatch):
    """Year should be populated by populate_movie_path for selected movies only (performance optimization)."""
    from subtrans.integrations.bazarr import get_wanted_movies, populate_movie_path

    # Mock wanted API response (doesn't include year)
    wanted_mock_data = {
        "data": [
            {
                "title": "2036 Origin Unknown",
                "radarrId": 1,
                "missing_subtitles": [{"code2": "fi"}],
                "subtitles": [{"code2": "en"}],
            },
            {
                "title": "The Matrix",
                "radarrId": 2,
                "missing_subtitles": [{"code2": "fi"}],
                "subtitles": [{"code2": "en"}],
            },
        ]
    }

    # Mock movies API response (includes year)
    movies_mock_data = {
        "data": [
            {
                "radarrId": 1,
                "year": 2018,
                "path": "/movies/2036 Origin Unknown (2018)/movie.mkv",
            },
            {
                "radarrId": 2,
                "year": 1999,
                "path": "/movies/The Matrix (1999)/movie.mkv",
            },
        ]
    }

    class MockResponse:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    class MockClient:
        def __init__(self):
            self.call_num = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            # Check if this is a wanted API call or movies API call
            url = args[0] if args else ""
            if "wanted" in url:
                # First call: wanted API
                return MockResponse(wanted_mock_data)
            else:
                # Subsequent calls: movies API (called for each selected movie only)
                return MockResponse(movies_mock_data)

    monkeypatch.setattr("httpx.Client", lambda **kwargs: MockClient())

    # Get movies (years will be 0 from wanted API - shown in selection UI)
    result = get_wanted_movies("http://test", "key", source_lang="en", target_lang="fi")
    assert len(result) == 2

    # Years should be 0 in selection UI (performance optimization - don't fetch all movies)
    assert result[0].year == 0, "Year from wanted API should be 0 in selection UI"
    assert result[1].year == 0, "Year from wanted API should be 0 in selection UI"
    assert result[0].display_title == "2036 Origin Unknown (0)", (
        "Selection UI shows (0) before population"
    )
    assert result[1].display_title == "The Matrix (0)", (
        "Selection UI shows (0) before population"
    )

    # Simulate user selecting first movie - populate details only for selected movie
    populate_movie_path(result[0], "http://test", "key")

    # Now first movie should have year, second still 0 (not selected)
    assert result[0].year == 2018, (
        "Selected movie year should be 2018 after populate_movie_path"
    )
    assert result[0].display_title == "2036 Origin Unknown (2018)", (
        "Selected movie display_title shows year"
    )
    assert result[1].year == 0, "Unselected movie year should still be 0"
    assert result[1].display_title == "The Matrix (0)", (
        "Unselected movie still shows (0)"
    )


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


def test_get_wanted_movies_accepts_bare_list_response(monkeypatch):
    """BazarrListResponse should lift a bare-list payload into the data field."""
    from subtrans.integrations.bazarr import get_wanted_movies

    bare_list = [
        {
            "title": "Bare List Movie",
            "year": 2024,
            "radarrId": 99,
            "missing_subtitles": [{"code2": "fi"}],
            "subtitles": [{"code2": "en"}],
        }
    ]
    _mock_httpx(monkeypatch, payload=bare_list)

    result = get_wanted_movies("http://test", "key", source_lang="en", target_lang="fi")

    assert len(result) == 1
    assert result[0].title == "Bare List Movie"


def test_get_wanted_episodes_parses_sxe_string(monkeypatch):
    """Wanted episodes should parse 'SxE' strings into season/episode ints."""
    from subtrans.integrations.bazarr import get_wanted_episodes

    payload = {
        "data": [
            {
                "sonarrEpisodeId": 1,
                "sonarrSeriesId": 10,
                "seriesTitle": "Show",
                "episodeTitle": "Pilot",
                "episode_number": "2x15",
                "missing_subtitles": [{"code2": "fi"}],
                "subtitles": [{"code2": "en"}],
            }
        ]
    }
    _mock_httpx(monkeypatch, payload=payload)

    result = get_wanted_episodes(
        "http://test", "key", source_lang="en", target_lang="fi"
    )

    assert len(result) == 1
    assert result[0].season_number == 2
    assert result[0].episode_number == 15


def test_get_wanted_episodes_handles_malformed_episode_number(monkeypatch, capsys):
    """Malformed 'SxE' strings default to (0, 0) and log once per item."""
    from subtrans.integrations.bazarr import get_wanted_episodes

    payload = {
        "data": [
            {
                "sonarrEpisodeId": 1,
                "sonarrSeriesId": 10,
                "seriesTitle": "Show",
                "episodeTitle": "Pilot",
                "episode_number": "garbage",
                "missing_subtitles": [{"code2": "fi"}],
                "subtitles": [{"code2": "en"}],
            }
        ]
    }
    _mock_httpx(monkeypatch, payload=payload)

    result = get_wanted_episodes(
        "http://test", "key", source_lang="en", target_lang="fi"
    )

    assert len(result) == 1
    assert result[0].season_number == 0
    assert result[0].episode_number == 0
    captured = capsys.readouterr()
    assert "garbage" in captured.out


def test_populate_episode_paths_bulk_groups_by_series(monkeypatch):
    """Bulk fetch should issue one HTTP call per unique series, not per episode."""
    from subtrans.core.models import Episode
    from subtrans.integrations.bazarr import populate_episode_paths_bulk

    episodes = [
        Episode(
            sonarr_id=1,
            series_name="Show A",
            season_number=0,
            episode_number=0,
            episode_title="Pilot",
            path="",
            missing_subtitles=["fi"],
            existing_subtitles=[],
            series_year=0,
            sonarr_series_id=100,
        ),
        Episode(
            sonarr_id=2,
            series_name="Show A",
            season_number=0,
            episode_number=0,
            episode_title="Second",
            path="",
            missing_subtitles=["fi"],
            existing_subtitles=[],
            series_year=0,
            sonarr_series_id=100,
        ),
        Episode(
            sonarr_id=3,
            series_name="Show B",
            season_number=0,
            episode_number=0,
            episode_title="Other",
            path="",
            missing_subtitles=["fi"],
            existing_subtitles=[],
            series_year=0,
            sonarr_series_id=200,
        ),
    ]

    series_payloads = {
        100: {
            "data": [
                {"sonarrEpisodeId": 1, "season": 1, "episode": 1, "path": "/A/1.mkv"},
                {"sonarrEpisodeId": 2, "season": 1, "episode": 2, "path": "/A/2.mkv"},
            ]
        },
        200: {
            "data": [
                {"sonarrEpisodeId": 3, "season": 1, "episode": 1, "path": "/B/1.mkv"},
            ]
        },
    }
    call_log: list[int] = []

    class MockResponse:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    class MockClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, headers=None, params=None):
            series_id = params["seriesid[]"]
            call_log.append(series_id)
            return MockResponse(series_payloads[series_id])

    monkeypatch.setattr("httpx.Client", lambda **kwargs: MockClient())

    populate_episode_paths_bulk(episodes, "http://test", "key")

    assert sorted(call_log) == [100, 200], (
        "expected one HTTP call per unique series, not per episode"
    )
    assert episodes[0].path == "/A/1.mkv"
    assert episodes[1].path == "/A/2.mkv"
    assert episodes[2].path == "/B/1.mkv"


def test_get_wanted_movies_skips_when_target_missing(monkeypatch):
    """Movies whose missing_subtitles do not include target_lang are filtered out."""
    from subtrans.integrations.bazarr import get_wanted_movies

    payload = {
        "data": [
            {
                "title": "Has Finnish Already",
                "year": 2020,
                "radarrId": 1,
                "missing_subtitles": [{"code2": "de"}],
                "subtitles": [{"code2": "en"}, {"code2": "fi"}],
            },
            {
                "title": "Needs Finnish",
                "year": 2020,
                "radarrId": 2,
                "missing_subtitles": [{"code2": "fi"}],
                "subtitles": [{"code2": "en"}],
            },
        ]
    }
    _mock_httpx(monkeypatch, payload=payload)

    result = get_wanted_movies("http://test", "key", source_lang="en", target_lang="fi")

    assert [m.title for m in result] == ["Needs Finnish"]
