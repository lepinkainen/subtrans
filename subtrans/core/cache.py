"""Cache management for extracted subtitles and translation context."""

import hashlib
import json
from pathlib import Path

from .media_types import is_episode, is_movie
from .models import ContextResponse, MediaItem, TranslationContext
from .utils import CACHE_DIR, console


def clear_cached_subtitle(srt_path: Path) -> bool:
    """Delete a cached SRT file if it lives inside ``CACHE_DIR``.

    Refuses to operate on paths outside the cache root, so callers don't
    accidentally remove the user's source SRT next to the video file.
    Returns True if a file was removed.
    """
    if CACHE_DIR not in srt_path.parents:
        return False
    srt_path.unlink(missing_ok=True)
    return True


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


def get_context_cache_path(media: MediaItem) -> Path:
    """
    Generate cache path for translation context.

    For movies: Uses {title}_{year}_context.json
    For episodes: Uses {series}_{season}_{episode}_{year}_context.json

    Args:
        media: Movie or Episode object

    Returns:
        Path to the cached context JSON file
    """
    if is_movie(media):
        # Sanitize title - keep only alphanumeric, spaces, and underscores
        safe_title = "".join(
            c for c in f"{media.title}_{media.year}" if c.isalnum() or c in (" ", "_")
        ).rstrip()
        # Replace spaces with underscores
        safe_title = safe_title.replace(" ", "_")
        return CACHE_DIR / f"{safe_title}_context.json"
    elif is_episode(media):
        # For episodes: series_name_S##E##_year_context.json
        safe_series = "".join(
            c for c in media.series_name if c.isalnum() or c in (" ", "_")
        ).rstrip()
        safe_series = safe_series.replace(" ", "_")
        return (
            CACHE_DIR
            / f"{safe_series}_S{media.season_number:02d}E{media.episode_number:02d}_{media.series_year}_context.json"
        )
    else:
        # Unreachable, but needed for type checking
        return CACHE_DIR / "unknown_context.json"


def load_cached_context(media: MediaItem) -> TranslationContext | None:
    """Load cached translation context if available.

    Returns ``None`` if the cache file is absent or unparseable; the caller
    will fall back to a fresh analysis pass.
    """
    context_path = get_context_cache_path(media)

    if not context_path.exists():
        return None

    try:
        raw_text = context_path.read_text(encoding="utf-8")
        parsed = ContextResponse.model_validate_json(raw_text)
        # Preserve the on-disk JSON for downstream code that reads `raw_json`
        # (notably the diff/edit prompts in workflows).
        raw_json = json.loads(raw_text)
        context = parsed.to_translation_context(raw_json=raw_json)
    except Exception as e:
        console.print(f"[yellow]Failed to load cached context: {e}[/yellow]")
        console.print("[blue]Running fresh analysis...[/blue]")
        return None

    console.print("[green]Using cached context from previous run[/green]")
    console.print(f"[dim]Cache: {context_path}[/dim]")
    console.print(
        f"[green]Loaded {len(context.characters)} characters, "
        f"{len(context.places)} places, "
        f"{len(context.terms)} recurring terms[/green]"
    )
    return context


def save_context_cache(context: TranslationContext, media: MediaItem) -> bool:
    """Persist a translation context to the cache directory.

    Returns True on success.
    """
    context_path = get_context_cache_path(media)
    try:
        context_path.write_text(
            json.dumps(context.raw_json, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        console.print(f"[dim]Saved context: {context_path}[/dim]")
        return True
    except Exception as e:
        console.print(f"[yellow]Failed to save context: {e}[/yellow]")
        return False
