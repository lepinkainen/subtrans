"""File output operations for translated subtitles."""

import re
from pathlib import Path

import pysrt

from ..core.utils import console, CACHE_DIR


def check_translation_exists(
    movie_path: str | Path,
    movie_title: str,
    movie_year: int,
    target_lang: str = "fi",
) -> tuple[bool, Path | None]:
    """
    Check if translated subtitle already exists.

    Checks both primary location (movie directory) and fallback cache.

    Args:
        movie_path: Path to movie file or directory
        movie_title: Movie title for cache lookup
        movie_year: Movie year for cache lookup
        target_lang: Target language code (default: "fi")

    Returns:
        Tuple of (exists: bool, found_path: Path | None)
    """
    from .subtitles import find_mkv_file

    # Check primary location (movie directory)
    # First verify the movie file exists (NAS might not be mounted)
    mkv_path = find_mkv_file(str(movie_path))
    if mkv_path and mkv_path.exists():
        # Movie file exists, check for translation
        primary_path = mkv_path.parent / f"{mkv_path.stem}.{target_lang}.srt"
        if primary_path.exists():
            return True, primary_path
    # If mkv_path doesn't exist, NAS likely not mounted - skip primary check

    # Check fallback cache location
    sanitized_title = re.sub(r"[^\w\s]", "", movie_title).replace(" ", "_")
    cache_path = CACHE_DIR / f"{sanitized_title}_{movie_year}.{target_lang}.srt"
    if cache_path.exists():
        return True, cache_path

    return False, None


def save_translated_subtitle(
    translated_subs: pysrt.SubRipFile,
    movie_path: str,
    mkv_path: Path | None = None,
    movie_title: str = "movie",
    movie_year: int = 0,
    target_lang: str = "fi",
) -> Path:
    """
    Save the translated subtitles with target language suffix (e.g., .fi.srt, .es.srt).

    Args:
        translated_subs: Translated subtitle file
        movie_path: Original movie path
        mkv_path: Path to MKV file (if known)
        movie_title: Movie title for fallback naming
        movie_year: Movie year for fallback naming
        target_lang: Target language code (ISO 639-1/2)

    Returns:
        Path where subtitle was saved
    """
    if mkv_path:
        # Use MKV filename as base
        output_path = mkv_path.parent / f"{mkv_path.stem}.{target_lang}.srt"
    else:
        # Use movie directory
        movie_dir = Path(movie_path)
        if movie_dir.is_file():
            output_path = movie_dir.parent / f"{movie_dir.stem}.{target_lang}.srt"
        else:
            # Find any video file
            for ext in [".mkv", ".mp4", ".avi"]:
                videos = list(movie_dir.glob(f"*{ext}"))
                if videos:
                    output_path = (
                        videos[0].parent / f"{videos[0].stem}.{target_lang}.srt"
                    )
                    break
            else:
                output_path = movie_dir / f"movie.{target_lang}.srt"

    # Try to save to the movie directory
    try:
        translated_subs.save(output_path, encoding="utf-8")
        return output_path
    except (PermissionError, OSError) as e:
        # If we can't write to NAS, save to local cache instead
        console.print(f"[yellow]Cannot write to {output_path}: {e}[/yellow]")
        safe_title = "".join(
            c for c in f"{movie_title}_{movie_year}" if c.isalnum() or c in (" ", "_")
        ).rstrip()
        safe_title = safe_title.replace(" ", "_")
        fallback_path = CACHE_DIR / f"{safe_title}.{target_lang}.srt"
        translated_subs.save(fallback_path, encoding="utf-8")
        console.print(f"[yellow]Saved to local cache instead: {fallback_path}[/yellow]")
        return fallback_path
