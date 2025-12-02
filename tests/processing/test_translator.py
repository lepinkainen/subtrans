"""Tests for translation logic."""

import pytest
from unittest.mock import Mock, MagicMock
import sys
from pathlib import Path

# Add the project root to path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from subtrans.processing.translator import analyze_subtitles, translate_subtitles_batch
from subtrans.core.models import TranslationContext


def test_analyze_subtitles_quota_error_exits_gracefully():
    """Test that quota errors in analysis phase exit gracefully."""
    from openai import RateLimitError
    import pysrt

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


def test_translate_subtitles_batch_quota_error_exits_gracefully():
    """Test that quota errors in translation phase exit gracefully."""
    from openai import RateLimitError
    import pysrt

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


def test_translate_subtitles_batch_other_errors_continue():
    """Test that non-quota errors keep original text and continue."""
    import pysrt

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
