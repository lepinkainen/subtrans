"""Tests for integrations.bazarr module."""


def test_has_source_subtitle_with_2letter_code():
    """Helper should detect 2-letter language codes."""
    from subtrans.integrations.bazarr import _has_source_subtitle

    subtitles = [{"code2": "en", "code3": "eng"}]
    has_source, found_langs = _has_source_subtitle(subtitles, "en")

    assert has_source is True
    assert "en" in found_langs


def test_has_source_subtitle_with_3letter_code():
    """Helper should detect 3-letter language codes."""
    from subtrans.integrations.bazarr import _has_source_subtitle

    subtitles = [{"code3": "eng"}]
    has_source, found_langs = _has_source_subtitle(subtitles, "en")

    assert has_source is True
    assert "eng" in found_langs


def test_has_source_subtitle_with_full_name():
    """Helper should detect full language names."""
    from subtrans.integrations.bazarr import _has_source_subtitle

    subtitles = [{"language": "English"}]
    has_source, found_langs = _has_source_subtitle(subtitles, "en")

    assert has_source is True
    assert "english" in found_langs


def test_has_source_subtitle_missing():
    """Helper should return False when source language is missing."""
    from subtrans.integrations.bazarr import _has_source_subtitle

    subtitles = [{"code2": "fr"}, {"code2": "de"}]
    has_source, found_langs = _has_source_subtitle(subtitles, "en")

    assert has_source is False
    assert found_langs == ["fr", "de"]


def test_has_source_subtitle_null_handling():
    """Helper should handle null/None values gracefully."""
    from subtrans.integrations.bazarr import _has_source_subtitle

    subtitles = [{"code2": None}, {"code3": None}, {"language": ""}]
    has_source, found_langs = _has_source_subtitle(subtitles, "en")

    assert has_source is False
    assert found_langs == []


def test_has_source_subtitle_case_insensitive():
    """Helper should be case-insensitive."""
    from subtrans.integrations.bazarr import _has_source_subtitle

    subtitles = [{"code2": "EN"}]
    has_source, found_langs = _has_source_subtitle(subtitles, "en")

    assert has_source is True
    assert "en" in found_langs


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
