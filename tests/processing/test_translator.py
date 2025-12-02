"""Tests for translation logic."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

# Add the project root to path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from subtrans.core.models import TranslationContext
from subtrans.processing.translator import analyze_subtitles, translate_subtitles_batch


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
