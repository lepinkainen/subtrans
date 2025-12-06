"""Token usage logging for cost tracking."""

import json
from datetime import datetime
from typing import Any

from .utils import CACHE_DIR, console


# Token usage log file location
TOKEN_LOG_FILE = CACHE_DIR / "token_usage.jsonl"


def log_token_usage(
    movie_title: str,
    movie_year: int,
    phase: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    batch_number: int | None = None,
) -> None:
    """
    Log token usage to JSON lines file for cost tracking.

    Args:
        movie_title: Title of the movie being translated
        movie_year: Year of the movie
        phase: "analysis" or "translation"
        model: OpenAI model name (e.g., "gpt-4o", "gpt-5")
        input_tokens: Number of input tokens consumed
        output_tokens: Number of output tokens consumed
        cached_tokens: Number of cached input tokens (for prompt caching)
        batch_number: Batch number for translation phase (None for analysis)
    """
    # Ensure cache directory exists
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Build log entry
    entry: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "movie_title": movie_title,
        "movie_year": movie_year,
        "phase": phase,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
    }

    # Add batch number for translation phase
    if batch_number is not None:
        entry["batch_number"] = batch_number

    # Append to log file (JSON lines format)
    try:
        with open(TOKEN_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to log token usage: {e}[/yellow]")


def get_token_usage_summary(movie_title: str | None = None) -> dict[str, Any]:
    """
    Get summary of token usage from log file.

    Args:
        movie_title: Optional filter by movie title

    Returns:
        Dictionary with usage statistics
    """
    if not TOKEN_LOG_FILE.exists():
        return {
            "total_entries": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cached_tokens": 0,
        }

    total_input = 0
    total_output = 0
    total_cached = 0
    entries = 0

    try:
        with open(TOKEN_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue

                entry = json.loads(line)

                # Filter by movie title if specified
                if movie_title and entry.get("movie_title") != movie_title:
                    continue

                entries += 1
                total_input += entry.get("input_tokens", 0)
                total_output += entry.get("output_tokens", 0)
                total_cached += entry.get("cached_tokens", 0)

        return {
            "total_entries": entries,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cached_tokens": total_cached,
        }
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to read token usage log: {e}[/yellow]")
        return {
            "total_entries": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cached_tokens": 0,
        }
