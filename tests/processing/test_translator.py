"""Tests for translation logic."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

# Add the project root to path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from subtrans.core.models import TranslationContext
from subtrans.processing.translator import (
    analyze_subtitles,
    translate_subtitles_batch,
    _calculate_text_similarity,
    _validate_translation_quality,
    _is_valid_translation_content,
    _parse_translation_response,
    _is_likely_separator,
)


def test_analyze_subtitles_quota_error_exits_gracefully(monkeypatch):
    """Test that quota errors in analysis phase exit gracefully."""
    from openai import RateLimitError
    import pysrt

    monkeypatch.setattr("subtrans.processing.translator._sleep", lambda *_: None)

    # Create mock client that raises RateLimitError
    mock_client = Mock()
    mock_client.chat.completions.create.side_effect = RateLimitError(
        message="Quota exceeded",
        response=MagicMock(status_code=429),
        body={"error": {"message": "Quota exceeded", "type": "insufficient_quota"}},
    )

    # Create simple subtitle file
    subs = pysrt.SubRipFile()
    subs.append(
        pysrt.SubRipItem(1, start="00:00:01,000", end="00:00:02,000", text="Hello")
    )

    # Should exit with SystemExit
    with pytest.raises(SystemExit) as exc_info:
        analyze_subtitles(subs, mock_client, "Test Movie", model="gpt-4o")

    assert exc_info.value.code == 1


def test_translate_subtitles_batch_quota_error_exits_gracefully(monkeypatch):
    """Test that quota errors in translation phase exit gracefully."""
    from openai import RateLimitError
    import pysrt

    monkeypatch.setattr("subtrans.processing.translator._sleep", lambda *_: None)

    # Create mock client that raises RateLimitError
    mock_client = Mock()
    mock_client.chat.completions.create.side_effect = RateLimitError(
        message="Quota exceeded",
        response=MagicMock(status_code=429),
        body={"error": {"message": "Quota exceeded", "type": "insufficient_quota"}},
    )

    # Create simple subtitle file
    subs = pysrt.SubRipFile()
    subs.append(
        pysrt.SubRipItem(1, start="00:00:01,000", end="00:00:02,000", text="Hello")
    )

    # Create simple context
    context = TranslationContext(
        characters={},
        places={},
        terms={},
        genre="action",
        tone="serious",
        formality="sinä",
        style_notes="",
        domains=[],
        domain_glossaries={},
        raw_json={},
    )

    # Should exit with SystemExit
    with pytest.raises(SystemExit) as exc_info:
        translate_subtitles_batch(
            subs,
            mock_client,
            "Test Movie",
            context=context,
            batch_size=50,
            model="gpt-4o",
        )

    assert exc_info.value.code == 1


def test_translate_subtitles_batch_other_errors_continue(monkeypatch):
    """Test that non-quota errors keep original text and continue."""
    import pysrt

    monkeypatch.setattr("subtrans.processing.translator._sleep", lambda *_: None)

    # Create mock client that raises generic exception
    mock_client = Mock()
    mock_client.chat.completions.create.side_effect = Exception("Network error")

    # Create simple subtitle file
    subs = pysrt.SubRipFile()
    subs.append(
        pysrt.SubRipItem(1, start="00:00:01,000", end="00:00:02,000", text="Hello")
    )
    subs.append(
        pysrt.SubRipItem(2, start="00:00:03,000", end="00:00:04,000", text="World")
    )

    # Should not raise, but return original text
    result = translate_subtitles_batch(
        subs, mock_client, "Test Movie", context=None, batch_size=50, model="gpt-4o"
    )

    # Should have same number of subtitles
    assert len(result) == 2
    # Text should be unchanged
    assert result[0].text == "Hello"
    assert result[1].text == "World"


def test_translate_subtitles_batch_partial_output_retries_and_keeps_original(
    monkeypatch,
):
    """Ensure partial responses trigger retry and fall back to originals."""
    import pysrt

    monkeypatch.setattr("subtrans.processing.translator._sleep", lambda *_: None)

    mock_client = Mock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "Translated first line only"
    # Two attempts, both return only one line to force fallback
    mock_client.chat.completions.create.side_effect = [response, response]

    subs = pysrt.SubRipFile()
    subs.append(
        pysrt.SubRipItem(1, start="00:00:01,000", end="00:00:02,000", text="Hello")
    )
    subs.append(
        pysrt.SubRipItem(2, start="00:00:03,000", end="00:00:04,000", text="World")
    )

    result = translate_subtitles_batch(
        subs, mock_client, "Test Movie", context=None, batch_size=2, model="gpt-4"
    )

    # Should have same number of subtitles
    assert len(result) == 2
    # Because responses were partial, originals should be kept
    assert result[0].text == "Hello"
    assert result[1].text == "World"
    # Should have attempted twice due to retry on partial output
    assert mock_client.chat.completions.create.call_count == 2


def test_calculate_text_similarity_identical():
    """Test similarity calculation for identical texts."""
    text1 = "Hello, world!"
    text2 = "Hello, world!"
    difference = _calculate_text_similarity(text1, text2)
    assert difference == 0.0  # Identical texts should have 0.0 difference


def test_calculate_text_similarity_completely_different():
    """Test similarity calculation for completely different texts."""
    text1 = "Hello"
    text2 = "Goodbye"
    difference = _calculate_text_similarity(text1, text2)
    assert difference > 0.5  # Very different texts should have high difference


def test_calculate_text_similarity_case_insensitive():
    """Test that similarity calculation is case-insensitive."""
    text1 = "HELLO WORLD"
    text2 = "hello world"
    difference = _calculate_text_similarity(text1, text2)
    assert difference == 0.0  # Case differences should not affect similarity


def test_calculate_text_similarity_empty_strings():
    """Test similarity calculation for empty strings."""
    # Both empty
    assert _calculate_text_similarity("", "") == 0.0
    # One empty
    assert _calculate_text_similarity("Hello", "") == 1.0
    assert _calculate_text_similarity("", "World") == 1.0


def test_validate_translation_quality_sufficient_difference():
    """Test validation passes when translation is sufficiently different."""
    original = "Hello, how are you?"
    translated = "Tervehdys, kuinka voit?"  # Completely different words
    is_valid, difference = _validate_translation_quality(
        original, translated, min_difference=0.6
    )
    assert is_valid
    assert difference >= 0.6


def test_validate_translation_quality_insufficient_difference():
    """Test validation fails when translation is too similar to original."""
    original = "Hello, world!"
    translated = "Hello, world!"
    is_valid, difference = _validate_translation_quality(
        original, translated, min_difference=0.8
    )
    assert not is_valid
    assert difference < 0.8


def test_validate_translation_quality_partial_translation():
    """Test validation with partially translated text."""
    original = "Hello, how are you today?"
    translated = "Hello, mitä kuuluu today?"  # Mix of English and Finnish
    is_valid, difference = _validate_translation_quality(
        original, translated, min_difference=0.8
    )
    # Should fail validation as it's too similar
    assert not is_valid


def test_translate_subtitles_batch_validation_warnings(monkeypatch, capsys):
    """Test that validation warnings are logged for untranslated batches."""
    import pysrt

    monkeypatch.setattr("subtrans.processing.translator._sleep", lambda *_: None)

    # Create mock client that returns English text (untranslated batch)
    mock_client = Mock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "Hello\n[NEXT]\nWorld"  # Same as input
    mock_client.chat.completions.create.return_value = response

    subs = pysrt.SubRipFile()
    subs.append(
        pysrt.SubRipItem(1, start="00:00:01,000", end="00:00:02,000", text="Hello")
    )
    subs.append(
        pysrt.SubRipItem(2, start="00:00:03,000", end="00:00:04,000", text="World")
    )

    # Call with validation enabled
    result = translate_subtitles_batch(
        subs,
        mock_client,
        "Test Movie",
        context=None,
        batch_size=2,
        model="gpt-4",
        validate_translation=True,
        min_translation_difference=0.8,
    )

    # Should still have translations (even if they failed validation)
    assert len(result) == 2
    # Text should be "translated" (but actually same as original)
    assert result[0].text == "Hello"
    assert result[1].text == "World"
    # Note: Warning is logged at batch level, not captured by capsys in this test


def test_translate_subtitles_batch_validation_disabled(monkeypatch):
    """Test that validation can be disabled."""
    import pysrt

    monkeypatch.setattr("subtrans.processing.translator._sleep", lambda *_: None)

    # Create mock client that returns English text
    mock_client = Mock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "Hello\n[NEXT]\nWorld"
    mock_client.chat.completions.create.return_value = response

    subs = pysrt.SubRipFile()
    subs.append(
        pysrt.SubRipItem(1, start="00:00:01,000", end="00:00:02,000", text="Hello")
    )
    subs.append(
        pysrt.SubRipItem(2, start="00:00:03,000", end="00:00:04,000", text="World")
    )

    # Call with validation disabled - should not raise warnings
    result = translate_subtitles_batch(
        subs,
        mock_client,
        "Test Movie",
        context=None,
        batch_size=2,
        model="gpt-4",
        validate_translation=False,  # Disabled
        min_translation_difference=0.8,
    )

    # Should still complete normally
    assert len(result) == 2


class TestIsLikelySeparator:
    """Tests for pattern-based separator detection."""

    # Valid separators (should return True)
    def test_detects_triple_dash(self):
        assert _is_likely_separator("---") is True

    def test_detects_triple_star(self):
        assert _is_likely_separator("***") is True

    def test_detects_triple_equals(self):
        assert _is_likely_separator("===") is True

    def test_detects_triple_plus(self):
        """NEW: unexpected format."""
        assert _is_likely_separator("+++") is True

    def test_detects_triple_hash(self):
        """NEW: unexpected format."""
        assert _is_likely_separator("###") is True

    def test_detects_long_dash_line(self):
        assert _is_likely_separator("----------") is True

    def test_detects_next_marker(self):
        assert _is_likely_separator("[NEXT]") is True

    def test_detects_empty(self):
        assert _is_likely_separator("") is True

    def test_detects_whitespace_only(self):
        assert _is_likely_separator("   ") is True

    def test_detects_triple_dot(self):
        assert _is_likely_separator("...") is True

    # Valid content (should return False)
    def test_accepts_finnish_text(self):
        assert _is_likely_separator("Hei maailma") is False

    def test_accepts_text_with_punctuation(self):
        assert _is_likely_separator("Mitä kuuluu?") is False

    def test_accepts_formatting_codes(self):
        assert _is_likely_separator("{\\an8}Terve") is False

    def test_accepts_mixed_content_with_dash(self):
        """Content that contains dashes but isn't a separator."""
        assert _is_likely_separator("Osa 1 - Alku") is False

    def test_accepts_single_word(self):
        assert _is_likely_separator("Kyllä") is False

    def test_accepts_numbers(self):
        assert _is_likely_separator("123") is False


class TestIsValidTranslationContent:
    """Tests for translation content validation."""

    def test_valid_finnish_text(self):
        assert _is_valid_translation_content("Hei maailma") is True

    def test_valid_with_punctuation(self):
        assert _is_valid_translation_content("Mitä kuuluu?") is True

    def test_valid_with_formatting(self):
        assert _is_valid_translation_content("{\\an8}Terve") is True

    def test_invalid_separator_dashes(self):
        assert _is_valid_translation_content("---") is False

    def test_invalid_separator_next(self):
        assert _is_valid_translation_content("[NEXT]") is False

    def test_invalid_empty(self):
        assert _is_valid_translation_content("") is False

    def test_invalid_whitespace_only(self):
        assert _is_valid_translation_content("   ") is False

    def test_invalid_dots(self):
        assert _is_valid_translation_content("...") is False

    def test_invalid_stars(self):
        assert _is_valid_translation_content("***") is False

    def test_invalid_equals(self):
        assert _is_valid_translation_content("===") is False

    def test_valid_single_word(self):
        assert _is_valid_translation_content("Kyllä") is True

    def test_valid_number(self):
        assert _is_valid_translation_content("123") is True

    def test_valid_mixed_content(self):
        assert _is_valid_translation_content("Osa 1 - Alku") is True


class TestParseTranslationResponse:
    """Tests for translation response parsing logic."""

    def test_parse_with_next_separator_newlines(self):
        """Standard [NEXT] separator with newlines."""
        response = "Hei\n[NEXT]\nMaailma\n[NEXT]\nTerve"
        result = _parse_translation_response(response, expected_count=3)
        assert result == ["Hei", "Maailma", "Terve"]

    def test_parse_with_next_separator_no_newlines(self):
        """[NEXT] separator without surrounding newlines."""
        response = "Hei[NEXT]Maailma[NEXT]Terve"
        result = _parse_translation_response(response, expected_count=3)
        assert result == ["Hei", "Maailma", "Terve"]

    def test_parse_with_markdown_separator(self):
        """Markdown --- separator (common GPT output)."""
        response = "Hei\n---\nMaailma\n---\nTerve"
        result = _parse_translation_response(response, expected_count=3)
        assert result == ["Hei", "Maailma", "Terve"]

    def test_parse_single_translation(self):
        """Single translation (no separator needed)."""
        response = "Tervetuloa"
        result = _parse_translation_response(response, expected_count=1)
        assert result == ["Tervetuloa"]

    def test_parse_preserves_formatting_codes(self):
        """SRT formatting codes like {\\an8} are preserved."""
        response = "{\\an8}Hei\n[NEXT]\n{\\an8}Maailma"
        result = _parse_translation_response(response, expected_count=2)
        assert result == ["{\\an8}Hei", "{\\an8}Maailma"]

    def test_parse_strips_whitespace(self):
        """Extra whitespace is stripped from translations."""
        response = "  Hei  \n[NEXT]\n  Maailma  "
        result = _parse_translation_response(response, expected_count=2)
        assert result == ["Hei", "Maailma"]

    def test_parse_count_mismatch_too_few(self):
        """Raises ValueError when fewer translations than expected."""
        response = "Hei\n[NEXT]\nMaailma"  # 2 translations
        with pytest.raises(ValueError, match="Expected 5 translations, got 2"):
            _parse_translation_response(response, expected_count=5)

    def test_parse_count_mismatch_too_many(self):
        """Raises ValueError when more translations than expected."""
        response = "Yksi\n[NEXT]\nKaksi\n[NEXT]\nKolme\n[NEXT]\nNeljä"
        with pytest.raises(ValueError, match="Expected 2 translations, got 4"):
            _parse_translation_response(response, expected_count=2)

    def test_parse_rejects_separator_as_content(self):
        """CRITICAL: '---' should not be accepted as translation content."""
        # Test that fallback newline splitter rejects "---" as content
        # This response has NO proper separators, so fallback is triggered
        # Fallback should filter out "---" lines
        response = "Hei\n---\nMaailma"
        # When split by \n, this gives ["Hei", "---", "Maailma"] = 3 items
        # Fallback filters "---", giving ["Hei", "Maailma"] = 2 items
        # If we expect 3 (including "---"), old code would have accepted it (THE BUG)
        # New code filters "---" and gets count mismatch
        with pytest.raises(ValueError, match="Expected 3 translations, got 2"):
            _parse_translation_response(response, expected_count=3)

    def test_parse_rejects_next_marker_as_content(self):
        """[NEXT] should not be accepted as translation content."""
        response = "Hei\n[NEXT]\n[NEXT]\nMaailma"  # Double [NEXT]
        with pytest.raises(ValueError):
            _parse_translation_response(response, expected_count=3)

    def test_parse_rejects_empty_translation(self):
        """Empty strings should not be accepted as translations."""
        response = "Hei\n[NEXT]\n\n[NEXT]\nMaailma"  # Empty middle
        with pytest.raises(ValueError):
            _parse_translation_response(response, expected_count=3)

    def test_parse_rejects_whitespace_only_translation(self):
        """Whitespace-only should not be accepted as translation."""
        response = "Hei\n[NEXT]\n   \n[NEXT]\nMaailma"
        with pytest.raises(ValueError):
            _parse_translation_response(response, expected_count=3)

    def test_parse_handles_mixed_separators(self):
        """Mixed separators should fail gracefully with count mismatch."""
        response = "Yksi\n[NEXT]\nKaksi\n---\nKolme"
        # Mixed separators can't be parsed correctly - will get count mismatch
        # Split by \n[NEXT]\n gets: ["Yksi", "Kaksi\n---\nKolme"] = 2 items
        # We expected 3, so this should raise ValueError
        with pytest.raises(ValueError, match="Expected 3 translations, got 2"):
            _parse_translation_response(response, expected_count=3)

    def test_parse_empty_response(self):
        """Empty response should raise ValueError."""
        with pytest.raises(ValueError):
            _parse_translation_response("", expected_count=1)

    def test_parse_with_plus_separator(self):
        """Handle +++ separator (unexpected format)."""
        response = "Hei\n+++\nMaailma\n+++\nTerve"
        # Fallback should filter +++ and extract 3 translations
        result = _parse_translation_response(response, expected_count=3)
        assert result == ["Hei", "Maailma", "Terve"]

    def test_parse_with_hash_separator(self):
        """Handle ### separator (unexpected format)."""
        response = "Yksi\n###\nKaksi\n###\nKolme"
        result = _parse_translation_response(response, expected_count=3)
        assert result == ["Yksi", "Kaksi", "Kolme"]

    def test_parse_with_equals_separator(self):
        """Handle === separator (unexpected format)."""
        response = "First\n===\nSecond"
        result = _parse_translation_response(response, expected_count=2)
        assert result == ["First", "Second"]

    def test_parse_with_long_separator(self):
        """Handle long separator lines."""
        response = "Hei\n----------\nMaailma"
        result = _parse_translation_response(response, expected_count=2)
        assert result == ["Hei", "Maailma"]


class TestTranslateSubtitlesBatchParsing:
    """Integration tests for batch translation parsing."""

    def test_batch_with_markdown_separators_parsed_correctly(self, monkeypatch):
        """Model returning --- separators should work."""
        import pysrt

        monkeypatch.setattr("subtrans.processing.translator._sleep", lambda *_: None)

        mock_client = Mock()
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "Hei\n---\nMaailma"
        response.usage = None
        mock_client.chat.completions.create.return_value = response

        subs = pysrt.SubRipFile()
        subs.append(
            pysrt.SubRipItem(1, start="00:00:01,000", end="00:00:02,000", text="Hello")
        )
        subs.append(
            pysrt.SubRipItem(2, start="00:00:03,000", end="00:00:04,000", text="World")
        )

        result = translate_subtitles_batch(subs, mock_client, "Test", batch_size=2)

        assert len(result) == 2
        assert result[0].text == "Hei"
        assert result[1].text == "Maailma"

    def test_batch_rejects_interleaved_separators_wrong_count(self, monkeypatch):
        """Separators interleaved with translations should be rejected."""
        import pysrt

        monkeypatch.setattr("subtrans.processing.translator._sleep", lambda *_: None)

        mock_client = Mock()
        response = MagicMock()
        # Bug pattern: N translations + N-1 separators = 2N-1 items
        # For batch of 4, model returns 2 translations + 2 separators = 4 items
        response.choices = [MagicMock()]
        response.choices[0].message.content = "Yksi\n---\nKaksi\n---"
        response.usage = None
        mock_client.chat.completions.create.return_value = response

        subs = pysrt.SubRipFile()
        for i in range(4):
            subs.append(
                pysrt.SubRipItem(
                    i + 1,
                    start=f"00:00:0{i},000",
                    end=f"00:00:0{i + 1},000",
                    text=f"Line {i + 1}",
                )
            )

        # Should fail and keep originals (retry exhausted)
        result = translate_subtitles_batch(subs, mock_client, "Test", batch_size=4)

        # Originals kept due to parse failure
        assert result[0].text == "Line 1"
