"""Token usage logging for cost tracking."""

import json
from datetime import datetime, date
from pathlib import Path
from typing import Any

import yaml

from .utils import CACHE_DIR, console


# Token usage log file location
TOKEN_LOG_FILE = CACHE_DIR / "token_usage.jsonl"

# Pricing configuration file
PRICING_FILE = Path(__file__).parent.parent / "pricing.yml"

# Cache for pricing data
_PRICING_DATA: dict[str, Any] | None = None


def log_token_usage(
    movie_title: str,
    movie_year: int,
    phase: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    batch_number: int | None = None,
    service_tier: str = "auto",
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
        service_tier: Service tier ("auto", "flex", "standard", "priority", "batch")
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
        "service_tier": service_tier,
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


def _load_pricing_data() -> dict[str, Any]:
    """
    Load pricing data from YAML file (with caching).

    Returns:
        Dictionary with pricing configuration
    """
    global _PRICING_DATA

    if _PRICING_DATA is not None:
        return _PRICING_DATA

    try:
        with open(PRICING_FILE, "r", encoding="utf-8") as f:
            _PRICING_DATA = yaml.safe_load(f)
            return _PRICING_DATA
    except FileNotFoundError:
        console.print(
            f"[yellow]Warning: Pricing file not found at {PRICING_FILE}[/yellow]"
        )
        return {
            "models": {},
            "service_tier_aliases": {},
            "fallback": {},
            "metadata": {},
        }
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to load pricing data: {e}[/yellow]")
        return {
            "models": {},
            "service_tier_aliases": {},
            "fallback": {},
            "metadata": {},
        }


def get_pricing_age_info() -> dict[str, Any]:
    """
    Get information about pricing data age.

    Returns:
        Dictionary with:
        - last_updated: date string (YYYY-MM-DD) or None
        - days_old: number of days since last update or None
        - is_current: True if less than 30 days old
    """
    pricing_data = _load_pricing_data()
    metadata = pricing_data.get("metadata", {})
    last_updated_str = metadata.get("last_updated")

    if not last_updated_str:
        return {
            "last_updated": None,
            "days_old": None,
            "is_current": False,
        }

    try:
        # Parse the date string (YYYY-MM-DD format)
        last_updated = datetime.strptime(last_updated_str, "%Y-%m-%d").date()
        today = date.today()
        days_old = (today - last_updated).days

        return {
            "last_updated": last_updated_str,
            "days_old": days_old,
            "is_current": days_old < 30,  # Consider current if less than 30 days old
        }
    except (ValueError, TypeError) as e:
        console.print(
            f"[yellow]Warning: Invalid date format in pricing data: {e}[/yellow]"
        )
        return {
            "last_updated": last_updated_str,
            "days_old": None,
            "is_current": False,
        }


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    service_tier: str = "auto",
) -> float:
    """
    Calculate cost for a specific API call based on token usage.

    Args:
        model: OpenAI model name (e.g., "gpt-4o", "gpt-5")
        input_tokens: Number of input tokens (excluding cached)
        output_tokens: Number of output tokens
        cached_tokens: Number of cached input tokens
        service_tier: Service tier ("auto", "flex", "standard", "priority", "batch")

    Returns:
        Total cost in USD
    """
    pricing_data = _load_pricing_data()

    # Resolve service tier aliases (e.g., "auto" -> "standard")
    tier_aliases = pricing_data.get("service_tier_aliases", {})
    resolved_tier = tier_aliases.get(service_tier, service_tier)

    # Get model pricing
    models = pricing_data.get("models", {})
    model_pricing = models.get(model)

    if not model_pricing:
        # Try to find fallback pricing
        fallback = pricing_data.get("fallback", {})
        if fallback:
            console.print(
                f"[yellow]Warning: Using fallback pricing for unknown model '{model}'[/yellow]"
            )
            input_price = fallback.get("input", 0) / 1_000_000  # Convert to per-token
            cached_price = (
                fallback.get("cached_input", input_price) / 1_000_000
            )  # Fallback to input price
            output_price = fallback.get("output", 0) / 1_000_000
        else:
            console.print(
                f"[yellow]Warning: No pricing data for model '{model}'[/yellow]"
            )
            return 0.0
    else:
        # Get tier-specific pricing
        tier_pricing = model_pricing.get(resolved_tier)

        if not tier_pricing:
            # Fall back to standard tier if specific tier not available
            console.print(
                f"[yellow]Warning: Tier '{resolved_tier}' not available for model '{model}', using standard[/yellow]"
            )
            tier_pricing = model_pricing.get("standard", {})

        if not tier_pricing:
            console.print(
                f"[yellow]Warning: No pricing data for model '{model}' tier '{resolved_tier}'[/yellow]"
            )
            return 0.0

        # Convert from per-1M tokens to per-token
        input_price = tier_pricing.get("input", 0) / 1_000_000
        cached_price = tier_pricing.get("cached_input", input_price) / 1_000_000
        output_price = tier_pricing.get("output", 0) / 1_000_000

    # Calculate total cost
    # Note: OpenAI returns total input_tokens including cached,
    # so we need to subtract cached from input to avoid double-counting
    non_cached_input = input_tokens - cached_tokens
    total_cost = (
        (non_cached_input * input_price)
        + (cached_tokens * cached_price)
        + (output_tokens * output_price)
    )

    return total_cost


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


def get_detailed_token_stats(
    movie_title: str | None = None,
) -> dict[str, Any]:
    """
    Get detailed token usage statistics with cost calculations.

    Args:
        movie_title: Optional filter by movie title

    Returns:
        Dictionary with detailed usage statistics including costs
    """
    if not TOKEN_LOG_FILE.exists():
        return {
            "total_movies": 0,
            "total_operations": 0,
            "total_cost": 0.0,
            "by_phase": {},
            "by_model": {},
            "by_movie": {},
        }

    # Track statistics
    movies: set[str] = set()
    operations = 0
    total_cost = 0.0
    by_phase: dict[str, Any] = {}
    by_model: dict[str, Any] = {}
    by_movie: dict[str, Any] = {}

    try:
        with open(TOKEN_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue

                entry = json.loads(line)

                # Filter by movie title if specified
                if movie_title and entry.get("movie_title") != movie_title:
                    continue

                operations += 1

                # Track unique movies
                movie_key = f"{entry.get('movie_title')} ({entry.get('movie_year')})"
                movies.add(movie_key)

                # Extract entry data
                model = entry.get("model", "unknown")
                phase = entry.get("phase", "unknown")
                input_tokens = entry.get("input_tokens", 0)
                output_tokens = entry.get("output_tokens", 0)
                cached_tokens = entry.get("cached_tokens", 0)

                # Get service tier from entry (with fallback for old log entries)
                service_tier = entry.get("service_tier")
                if not service_tier:
                    # Fallback for old log entries without service_tier field
                    service_tier = "flex" if phase == "translation" else "auto"
                cost = calculate_cost(
                    model, input_tokens, output_tokens, cached_tokens, service_tier
                )
                total_cost += cost

                # Track by phase
                if phase not in by_phase:
                    by_phase[phase] = {
                        "operations": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cached_tokens": 0,
                        "cost": 0.0,
                    }
                by_phase[phase]["operations"] += 1
                by_phase[phase]["input_tokens"] += input_tokens
                by_phase[phase]["output_tokens"] += output_tokens
                by_phase[phase]["cached_tokens"] += cached_tokens
                by_phase[phase]["cost"] += cost

                # Track by model
                if model not in by_model:
                    by_model[model] = {
                        "operations": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cached_tokens": 0,
                        "cost": 0.0,
                    }
                by_model[model]["operations"] += 1
                by_model[model]["input_tokens"] += input_tokens
                by_model[model]["output_tokens"] += output_tokens
                by_model[model]["cached_tokens"] += cached_tokens
                by_model[model]["cost"] += cost

                # Track by movie
                if movie_key not in by_movie:
                    by_movie[movie_key] = {
                        "operations": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cached_tokens": 0,
                        "cost": 0.0,
                    }
                by_movie[movie_key]["operations"] += 1
                by_movie[movie_key]["input_tokens"] += input_tokens
                by_movie[movie_key]["output_tokens"] += output_tokens
                by_movie[movie_key]["cached_tokens"] += cached_tokens
                by_movie[movie_key]["cost"] += cost

        return {
            "total_movies": len(movies),
            "total_operations": operations,
            "total_cost": total_cost,
            "by_phase": by_phase,
            "by_model": by_model,
            "by_movie": by_movie,
        }
    except Exception as e:
        console.print(
            f"[yellow]Warning: Failed to read detailed token usage: {e}[/yellow]"
        )
        return {
            "total_movies": 0,
            "total_operations": 0,
            "total_cost": 0.0,
            "by_phase": {},
            "by_model": {},
            "by_movie": {},
        }
