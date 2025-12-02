"""Tests for processing.subtitles module."""


def test_find_mkv_file_direct(tmp_path):
    """Should find MKV when path IS the MKV file."""
    from subtrans.processing.subtitles import find_mkv_file

    mkv = tmp_path / "movie.mkv"
    mkv.touch()

    result = find_mkv_file(str(mkv))
    assert result == mkv


def test_find_mkv_file_largest(tmp_path):
    """Should return largest MKV in directory."""
    from subtrans.processing.subtitles import find_mkv_file

    (tmp_path / "movie.mkv").write_bytes(b"x" * 1000)
    (tmp_path / "sample.mkv").write_bytes(b"x" * 100)

    result = find_mkv_file(str(tmp_path))
    assert result.name == "movie.mkv"


def test_find_mkv_file_not_found(tmp_path):
    """Should return None if no MKV files."""
    from subtrans.processing.subtitles import find_mkv_file

    result = find_mkv_file(str(tmp_path))
    assert result is None


def test_find_external_srt_english(tmp_path):
    """Should find English SRT files."""
    from subtrans.processing.subtitles import find_external_srt

    (tmp_path / "movie.en.srt").touch()

    result = find_external_srt(tmp_path)
    assert result is not None
    assert result.name == "movie.en.srt"


def test_find_external_srt_uppercase(tmp_path):
    """Should find uppercase English SRT files."""
    from subtrans.processing.subtitles import find_external_srt

    (tmp_path / "movie.EN.srt").touch()

    result = find_external_srt(tmp_path)
    assert result is not None
    assert result.name == "movie.EN.srt"


def test_find_external_srt_english_pattern(tmp_path):
    """Should find English pattern SRT files."""
    from subtrans.processing.subtitles import find_external_srt

    (tmp_path / "movie.english.srt").touch()

    result = find_external_srt(tmp_path)
    assert result is not None
    assert result.name == "movie.english.srt"


def test_find_external_srt_fallback(tmp_path):
    """Should return None when SRT exists but doesn't match language pattern."""
    from subtrans.processing.subtitles import find_external_srt

    (tmp_path / "movie.srt").touch()

    result = find_external_srt(tmp_path)
    # Returns None to trigger embedded subtitle search
    assert result is None


def test_find_external_srt_not_found(tmp_path):
    """Should return None if no SRT files."""
    from subtrans.processing.subtitles import find_external_srt

    result = find_external_srt(tmp_path)
    assert result is None
