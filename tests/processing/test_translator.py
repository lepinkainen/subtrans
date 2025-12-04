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
