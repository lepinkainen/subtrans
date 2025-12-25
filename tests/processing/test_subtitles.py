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


def test_validate_subtitle_file_valid(tmp_path):
    """Should pass validation for valid subtitle file."""
    from subtrans.processing.subtitles import validate_subtitle_file

    # Create valid SRT file with 100 entries (exceeds min of 50)
    srt_file = tmp_path / "valid.srt"
    entries = []
    for i in range(1, 101):
        entries.append(f"{i}\n")
        entries.append(f"00:00:{i:02d},000 --> 00:00:{i:02d},500\n")
        entries.append(f"Subtitle entry {i}\n")
        entries.append("\n")
    srt_file.write_text("".join(entries), encoding="utf-8")

    is_valid, entry_count, error_msg = validate_subtitle_file(srt_file)

    assert is_valid is True
    assert entry_count == 100
    assert error_msg == ""


def test_validate_subtitle_file_too_small(tmp_path):
    """Should fail validation for tiny file."""
    from subtrans.processing.subtitles import validate_subtitle_file

    # Create file smaller than 2KB minimum
    srt_file = tmp_path / "tiny.srt"
    srt_file.write_text("1\n00:00:01,000 --> 00:00:02,000\nTest\n", encoding="utf-8")

    is_valid, entry_count, error_msg = validate_subtitle_file(srt_file)

    assert is_valid is False
    assert entry_count == 0
    assert "too small" in error_msg
    assert "2048" in error_msg


def test_validate_subtitle_file_too_few_entries(tmp_path):
    """Should fail validation for low entry count."""
    from subtrans.processing.subtitles import validate_subtitle_file

    # Create file with only 5 entries (below min of 50)
    # Make it large enough to pass file size check
    srt_file = tmp_path / "few_entries.srt"
    entries = []
    for i in range(1, 6):
        # Add padding to make file > 2KB
        padding = "x" * 500
        entries.append(f"{i}\n")
        entries.append(f"00:00:{i:02d},000 --> 00:00:{i:02d},500\n")
        entries.append(f"Subtitle entry {i} {padding}\n")
        entries.append("\n")
    srt_file.write_text("".join(entries), encoding="utf-8")

    is_valid, entry_count, error_msg = validate_subtitle_file(srt_file)

    assert is_valid is False
    assert entry_count == 5
    assert "only 5 entries" in error_msg
    assert "minimum 50 expected" in error_msg


def test_validate_subtitle_file_nonexistent(tmp_path):
    """Should fail validation for missing file."""
    from subtrans.processing.subtitles import validate_subtitle_file

    nonexistent = tmp_path / "nonexistent.srt"

    is_valid, entry_count, error_msg = validate_subtitle_file(nonexistent)

    assert is_valid is False
    assert entry_count == 0
    assert "does not exist" in error_msg


def test_validate_subtitle_file_encoding_fallback(tmp_path):
    """Should handle non-UTF8 files with encoding fallback."""
    from subtrans.processing.subtitles import validate_subtitle_file

    # Create file with latin-1 encoding
    srt_file = tmp_path / "latin1.srt"
    entries = []
    for i in range(1, 101):
        entries.append(f"{i}\n")
        entries.append(f"00:00:{i:02d},000 --> 00:00:{i:02d},500\n")
        entries.append("Subtitle with special char: \xe9\n")  # latin-1 é
        entries.append("\n")
    srt_file.write_bytes("".join(entries).encode("latin-1"))

    is_valid, entry_count, error_msg = validate_subtitle_file(srt_file)

    assert is_valid is True
    assert entry_count == 100
    assert error_msg == ""


def test_validate_subtitle_file_empty(tmp_path):
    """Should fail validation for file with zero entries."""
    from subtrans.processing.subtitles import validate_subtitle_file

    # Create file large enough but with no valid entries
    srt_file = tmp_path / "empty.srt"
    srt_file.write_text("x" * 3000, encoding="utf-8")  # Just garbage data

    is_valid, entry_count, error_msg = validate_subtitle_file(srt_file)

    assert is_valid is False
    assert entry_count == 0
    assert "no subtitle entries" in error_msg


def test_validate_subtitle_file_custom_thresholds(tmp_path):
    """Should respect custom validation thresholds."""
    from subtrans.processing.subtitles import validate_subtitle_file

    # Create file with 15 entries
    srt_file = tmp_path / "custom.srt"
    entries = []
    for i in range(1, 16):
        padding = "x" * 200
        entries.append(f"{i}\n")
        entries.append(f"00:00:{i:02d},000 --> 00:00:{i:02d},500\n")
        entries.append(f"Entry {i} {padding}\n")
        entries.append("\n")
    srt_file.write_text("".join(entries), encoding="utf-8")

    # Should fail with default threshold of 50
    is_valid, entry_count, error_msg = validate_subtitle_file(srt_file)
    assert is_valid is False
    assert entry_count == 15

    # Should pass with custom threshold of 10
    is_valid, entry_count, error_msg = validate_subtitle_file(srt_file, min_entries=10)
    assert is_valid is True
    assert entry_count == 15
    assert error_msg == ""
