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
