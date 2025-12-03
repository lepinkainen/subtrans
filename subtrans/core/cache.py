"""Cache management for extracted subtitles and translation context."""

import hashlib
import json
from pathlib import Path
from typing import Optional

from .models import TranslationContext
from .utils import CACHE_DIR, console


def get_subtitle_cache_path(mkv_path: Path, track_id: int) -> Path:
    """
    Generate cache path for extracted subtitle.

    Uses MD5 hash of "{mkv_path}:{track_id}" to create unique, consistent cache filename.

    Args:
        mkv_path: Path to the MKV file
        track_id: Subtitle track ID

    Returns:
        Path to the cached subtitle file
    """
    cache_key = hashlib.md5(f"{mkv_path}:{track_id}".encode()).hexdigest()
    return CACHE_DIR / f"{cache_key}.srt"


def get_context_cache_path(movie_title: str, movie_year: int) -> Path:
    """
    Generate cache path for translation context.

    Sanitizes movie title to create a safe filename.

    Args:
        movie_title: Movie title
        movie_year: Movie year

    Returns:
        Path to the cached context JSON file
    """
    # Sanitize title - keep only alphanumeric, spaces, and underscores
    safe_title = "".join(
        c for c in f"{movie_title}_{movie_year}" if c.isalnum() or c in (" ", "_")
    ).rstrip()

    # Replace spaces with underscores
    safe_title = safe_title.replace(" ", "_")

    return CACHE_DIR / f"{safe_title}_context.json"


def load_cached_context(
    movie_title: str, movie_year: int
) -> Optional[TranslationContext]:
    """
    Load cached translation context if available.

    Args:
        movie_title: Movie title
        movie_year: Movie year

    Returns:
        TranslationContext if cache exists and is valid, None otherwise
    """
    context_path = get_context_cache_path(movie_title, movie_year)

    if not context_path.exists():
        return None

    try:
        with open(context_path, "r", encoding="utf-8") as f:
            cached_data = json.load(f)

        context = TranslationContext(
            characters=cached_data.get("characters", {}),
            places=cached_data.get("places", {}),
            terms=cached_data.get("recurring_terms", {}),
            genre=cached_data.get("genre", "unknown"),
            tone=cached_data.get("tone", "mixed"),
            formality=cached_data.get("formality_recommendation", "sinä"),
            style_notes=cached_data.get("style_notes", ""),
            domains=cached_data.get("domains", []),
            domain_glossaries=cached_data.get("domain_glossaries", {}),
            raw_json=cached_data,
        )

        console.print("[green]Using cached context from previous run[/green]")
        console.print(f"[dim]Cache: {context_path}[/dim]")
        console.print(
            f"[green]Loaded {len(context.characters)} characters, "
            f"{len(context.places)} places, "
            f"{len(context.terms)} recurring terms[/green]"
        )

        return context

    except Exception as e:
        console.print(f"[yellow]Failed to load cached context: {e}[/yellow]")
        console.print("[blue]Running fresh analysis...[/blue]")
        return None


def save_context_cache(
    context: TranslationContext, movie_title: str, movie_year: int
) -> bool:
    """
    Save translation context to cache.

    Args:
        context: Translation context to save
        movie_title: Movie title
        movie_year: Movie year

    Returns:
        True if save successful, False otherwise
    """
    context_path = get_context_cache_path(movie_title, movie_year)

    try:
        with open(context_path, "w", encoding="utf-8") as f:
            json.dump(context.raw_json, f, indent=2, ensure_ascii=False)
        console.print(f"[dim]Saved context: {context_path}[/dim]")
        return True
    except Exception as e:
        console.print(f"[yellow]Failed to save context: {e}[/yellow]")
        return False
