"""Tests for token_logger module."""

import json
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from subtrans.core.token_logger import (
    calculate_cost,
    get_detailed_token_stats,
    get_pricing_age_info,
    log_token_usage,
)


@pytest.fixture
def temp_token_log(tmp_path, monkeypatch):
    """Create temporary token log file for testing."""
    temp_log = tmp_path / "token_usage.jsonl"
    monkeypatch.setattr("subtrans.core.token_logger.TOKEN_LOG_FILE", temp_log)
    monkeypatch.setattr("subtrans.core.token_logger.CACHE_DIR", tmp_path)
    return temp_log


def test_calculate_cost_gpt5_standard():
    """Test cost calculation for gpt-5 with standard tier."""
    # gpt-5 standard: input=$1.25/1M, cached=$0.125/1M, output=$10.00/1M
    cost = calculate_cost(
        model="gpt-5",
        input_tokens=100_000,  # $0.125
        output_tokens=10_000,  # $0.10
        cached_tokens=0,
        service_tier="auto",  # maps to standard
    )
    # Expected: (100k * 1.25 / 1M) + (10k * 10.00 / 1M) = 0.125 + 0.10 = 0.225
    assert abs(cost - 0.225) < 0.0001


def test_calculate_cost_gpt5_flex():
    """Test cost calculation for gpt-5 with flex tier (50% discount)."""
    # gpt-5 flex: input=$0.625/1M, cached=$0.0625/1M, output=$5.00/1M
    cost = calculate_cost(
        model="gpt-5",
        input_tokens=100_000,  # 100k non-cached input
        output_tokens=10_000,
        cached_tokens=50_000,  # 50k cached
        service_tier="flex",
    )
    # Expected: (50k * 0.625 / 1M) + (50k * 0.0625 / 1M) + (10k * 5.00 / 1M)
    #         = 0.03125 + 0.003125 + 0.05 = 0.084375
    assert abs(cost - 0.084375) < 0.0001


def test_calculate_cost_with_cached_tokens():
    """Test that cached tokens are properly discounted."""
    # gpt-4o standard: input=$2.50/1M, cached=$1.25/1M, output=$10.00/1M
    cost = calculate_cost(
        model="gpt-4o",
        input_tokens=100_000,  # Total input includes cached
        output_tokens=10_000,
        cached_tokens=60_000,  # 60k cached, 40k fresh
        service_tier="standard",
    )
    # Expected: (40k * 2.50 / 1M) + (60k * 1.25 / 1M) + (10k * 10.00 / 1M)
    #         = 0.10 + 0.075 + 0.10 = 0.275
    assert abs(cost - 0.275) < 0.0001


def test_calculate_cost_unknown_model():
    """Test fallback pricing for unknown model."""
    cost = calculate_cost(
        model="unknown-model",
        input_tokens=100_000,
        output_tokens=10_000,
        cached_tokens=0,
        service_tier="standard",
    )
    # Should use fallback: input=$2.50/1M, output=$10.00/1M
    # Expected: (100k * 2.50 / 1M) + (10k * 10.00 / 1M) = 0.25 + 0.10 = 0.35
    assert abs(cost - 0.35) < 0.0001


def test_log_token_usage(temp_token_log):
    """Test logging token usage to file."""
    log_token_usage(
        movie_title="Test Movie",
        movie_year=2024,
        phase="analysis",
        model="gpt-5",
        input_tokens=1000,
        output_tokens=500,
        cached_tokens=200,
        service_tier="auto",
    )

    # Verify log file was created and contains correct data
    assert temp_token_log.exists()

    with open(temp_token_log, "r", encoding="utf-8") as f:
        entry = json.loads(f.readline())

    assert entry["movie_title"] == "Test Movie"
    assert entry["movie_year"] == 2024
    assert entry["phase"] == "analysis"
    assert entry["model"] == "gpt-5"
    assert entry["input_tokens"] == 1000
    assert entry["output_tokens"] == 500
    assert entry["cached_tokens"] == 200
    assert entry["service_tier"] == "auto"
    assert "timestamp" in entry


def test_log_token_usage_with_batch_number(temp_token_log):
    """Test logging token usage with batch number."""
    log_token_usage(
        movie_title="Test Movie",
        movie_year=2024,
        phase="translation",
        model="gpt-5",
        input_tokens=1000,
        output_tokens=500,
        batch_number=5,
        service_tier="flex",
    )

    with open(temp_token_log, "r", encoding="utf-8") as f:
        entry = json.loads(f.readline())

    assert entry["batch_number"] == 5


def test_get_detailed_stats_empty(temp_token_log):
    """Test getting stats when no data exists."""
    stats = get_detailed_token_stats()

    assert stats["total_movies"] == 0
    assert stats["total_operations"] == 0
    assert stats["total_cost"] == 0.0
    assert len(stats["by_phase"]) == 0
    assert len(stats["by_model"]) == 0
    assert len(stats["by_movie"]) == 0


def test_get_detailed_stats_with_data(temp_token_log):
    """Test getting detailed stats with logged data."""
    # Log some test data
    log_token_usage(
        movie_title="Movie A",
        movie_year=2024,
        phase="analysis",
        model="gpt-5",
        input_tokens=100_000,
        output_tokens=10_000,
        cached_tokens=0,
        service_tier="auto",
    )

    log_token_usage(
        movie_title="Movie A",
        movie_year=2024,
        phase="translation",
        model="gpt-5",
        input_tokens=200_000,
        output_tokens=50_000,
        cached_tokens=100_000,
        batch_number=1,
        service_tier="flex",
    )

    log_token_usage(
        movie_title="Movie B",
        movie_year=2023,
        phase="analysis",
        model="gpt-4o",
        input_tokens=50_000,
        output_tokens=5_000,
        cached_tokens=0,
        service_tier="standard",
    )

    stats = get_detailed_token_stats()

    # Check overall stats
    assert stats["total_movies"] == 2
    assert stats["total_operations"] == 3
    assert stats["total_cost"] > 0

    # Check by phase
    assert "analysis" in stats["by_phase"]
    assert "translation" in stats["by_phase"]
    assert stats["by_phase"]["analysis"]["operations"] == 2
    assert stats["by_phase"]["translation"]["operations"] == 1

    # Check by model
    assert "gpt-5" in stats["by_model"]
    assert "gpt-4o" in stats["by_model"]
    assert stats["by_model"]["gpt-5"]["operations"] == 2
    assert stats["by_model"]["gpt-4o"]["operations"] == 1

    # Check by movie
    assert "Movie A (2024)" in stats["by_movie"]
    assert "Movie B (2023)" in stats["by_movie"]
    assert stats["by_movie"]["Movie A (2024)"]["operations"] == 2
    assert stats["by_movie"]["Movie B (2023)"]["operations"] == 1


def test_get_detailed_stats_with_filter(temp_token_log):
    """Test filtering stats by movie title."""
    # Log data for multiple movies
    log_token_usage(
        movie_title="Movie A",
        movie_year=2024,
        phase="analysis",
        model="gpt-5",
        input_tokens=100_000,
        output_tokens=10_000,
        service_tier="auto",
    )

    log_token_usage(
        movie_title="Movie B",
        movie_year=2023,
        phase="analysis",
        model="gpt-5",
        input_tokens=50_000,
        output_tokens=5_000,
        service_tier="auto",
    )

    # Filter by Movie A
    stats = get_detailed_token_stats(movie_title="Movie A")

    assert stats["total_movies"] == 1
    assert stats["total_operations"] == 1
    assert "Movie A (2024)" in stats["by_movie"]
    assert "Movie B (2023)" not in stats["by_movie"]


def test_get_detailed_stats_with_legacy_log_entries(temp_token_log):
    """Test handling legacy log entries without service_tier field."""
    # Manually create a legacy log entry without service_tier
    with open(temp_token_log, "w", encoding="utf-8") as f:
        entry = {
            "timestamp": "2024-01-01T12:00:00",
            "movie_title": "Legacy Movie",
            "movie_year": 2020,
            "phase": "translation",
            "model": "gpt-5",
            "input_tokens": 100_000,
            "output_tokens": 10_000,
            "cached_tokens": 0,
            # No service_tier field
        }
        f.write(json.dumps(entry) + "\n")

    stats = get_detailed_token_stats()

    # Should infer service_tier from phase
    assert stats["total_operations"] == 1
    assert stats["total_cost"] > 0  # Should calculate cost using inferred tier


def test_get_pricing_age_info_current():
    """Test pricing age info for current pricing data."""
    # Mock today's date
    today = date.today()
    mock_pricing_data = {
        "metadata": {
            "last_updated": today.strftime("%Y-%m-%d"),
        },
    }

    with patch(
        "subtrans.core.token_logger._load_pricing_data", return_value=mock_pricing_data
    ):
        info = get_pricing_age_info()

        assert info["last_updated"] == today.strftime("%Y-%m-%d")
        assert info["days_old"] == 0
        assert info["is_current"] is True


def test_get_pricing_age_info_one_week_old():
    """Test pricing age info for one week old data."""
    today = date.today()
    one_week_ago = today - timedelta(days=7)
    mock_pricing_data = {
        "metadata": {
            "last_updated": one_week_ago.strftime("%Y-%m-%d"),
        },
    }

    with patch(
        "subtrans.core.token_logger._load_pricing_data", return_value=mock_pricing_data
    ):
        info = get_pricing_age_info()

        assert info["last_updated"] == one_week_ago.strftime("%Y-%m-%d")
        assert info["days_old"] == 7
        assert info["is_current"] is True  # Still current (< 30 days)


def test_get_pricing_age_info_old():
    """Test pricing age info for old pricing data."""
    today = date.today()
    old_date = today - timedelta(days=60)
    mock_pricing_data = {
        "metadata": {
            "last_updated": old_date.strftime("%Y-%m-%d"),
        },
    }

    with patch(
        "subtrans.core.token_logger._load_pricing_data", return_value=mock_pricing_data
    ):
        info = get_pricing_age_info()

        assert info["last_updated"] == old_date.strftime("%Y-%m-%d")
        assert info["days_old"] == 60
        assert info["is_current"] is False  # Not current (>= 30 days)


def test_get_pricing_age_info_missing_metadata():
    """Test pricing age info when metadata is missing."""
    mock_pricing_data = {
        # No metadata field
    }

    with patch(
        "subtrans.core.token_logger._load_pricing_data", return_value=mock_pricing_data
    ):
        info = get_pricing_age_info()

        assert info["last_updated"] is None
        assert info["days_old"] is None
        assert info["is_current"] is False


def test_get_pricing_age_info_invalid_date_format():
    """Test pricing age info with invalid date format."""
    mock_pricing_data = {
        "metadata": {
            "last_updated": "invalid-date",
        },
    }

    with patch(
        "subtrans.core.token_logger._load_pricing_data", return_value=mock_pricing_data
    ):
        info = get_pricing_age_info()

        assert info["last_updated"] == "invalid-date"
        assert info["days_old"] is None
        assert info["is_current"] is False
