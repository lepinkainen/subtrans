"""File output operations for translated subtitles."""

import re
from pathlib import Path

import pysrt

from ..core.utils import console, CACHE_DIR
from ..core.media_types import is_episode, is_movie
from ..core.models import MediaItem


def check_translation_exists(
    media: MediaItem,
    target_lang: str = "fi",
) -> tuple[bool, Path | None]:
    """
    Check if translated subtitle already exists.

    Checks both primary location (media file directory) and fallback cache.

    Args:
        media: Movie or Episode object to check
        target_lang: Target language code (default: "fi")

    Returns:
        Tuple of (exists: bool, found_path: Path | None)
    """
    from .subtitles import find_mkv_file

    # Check primary location (media file directory)
    # First verify the media file exists (NAS might not be mounted)
    mkv_path = find_mkv_file(media.file_path)
    if mkv_path and mkv_path.exists():
        # Media file exists, check for translation
        # Use original filename stem for both movies and episodes
        filename = f"{mkv_path.stem}.{target_lang}.srt"
        primary_path = mkv_path.parent / filename
        if primary_path.exists():
            return True, primary_path
    # If mkv_path doesn't exist, NAS likely not mounted - skip primary check

    # Check fallback cache location
    if is_movie(media):
        sanitized_title = re.sub(r"[^\w\s]", "", media.title).replace(" ", "_")
        cache_path = CACHE_DIR / f"{sanitized_title}_{media.year}.{target_lang}.srt"
    elif is_episode(media):
        sanitized_series = re.sub(r"[^\w\s]", "", media.series_name).replace(" ", "_")
        cache_path = (
            CACHE_DIR
            / f"{sanitized_series}_S{media.season_number:02d}E{media.episode_number:02d}.{target_lang}.srt"
        )
    else:
        # Unreachable, but needed for type checking
        return False, None

    if cache_path.exists():
        return True, cache_path

    return False, None


def save_translated_subtitle(
    translated_subs: pysrt.SubRipFile,
    media: MediaItem,
    mkv_path: Path | None = None,
    target_lang: str = "fi",
) -> Path:
    """
    Save the translated subtitles with target language suffix (e.g., .fi.srt, .es.srt).

    Args:
        translated_subs: Translated subtitle file
        media: Movie or Episode object
        mkv_path: Path to MKV file (if known)
        target_lang: Target language code (ISO 639-1/2)

    Returns:
        Path where subtitle was saved
    """
    if mkv_path:
        # Use MKV filename as base - preserve exact original filename
        filename = f"{mkv_path.stem}.{target_lang}.srt"
        output_path = mkv_path.parent / filename
    else:
        # Use media directory
        media_dir = Path(media.file_path)
        if media_dir.is_file():
            # Use original filename stem for both movies and episodes
            filename = f"{media_dir.stem}.{target_lang}.srt"
            output_path = media_dir.parent / filename
        else:
            # Find any video file
            for ext in [".mkv", ".mp4", ".avi"]:
                videos = list(media_dir.glob(f"*{ext}"))
                if videos:
                    # Use original filename stem for both movies and episodes
                    filename = f"{videos[0].stem}.{target_lang}.srt"
                    output_path = videos[0].parent / filename
                    break
            else:
                # No video file found - use generic fallback naming
                if is_movie(media):
                    output_path = media_dir / f"movie.{target_lang}.srt"
                elif is_episode(media):
                    sanitized_series = re.sub(
                        r"[^\w\s]", "", media.series_name
                    ).replace(" ", ".")
                    output_path = (
                        media_dir
                        / f"{sanitized_series}.S{media.season_number:02d}E{media.episode_number:02d}.{target_lang}.srt"
                    )
                else:
                    # Unreachable, but needed for type checking
                    output_path = media_dir / f"unknown.{target_lang}.srt"

    # Try to save to the media directory
    try:
        translated_subs.save(output_path, encoding="utf-8")
        return output_path
    except (PermissionError, OSError) as e:
        # If we can't write to NAS, save to local cache instead
        console.print(f"[yellow]Cannot write to {output_path}: {e}[/yellow]")
        if is_movie(media):
            safe_title = "".join(
                c
                for c in f"{media.title}_{media.year}"
                if c.isalnum() or c in (" ", "_")
            ).rstrip()
            safe_title = safe_title.replace(" ", "_")
            fallback_path = CACHE_DIR / f"{safe_title}.{target_lang}.srt"
        elif is_episode(media):
            sanitized_series = re.sub(r"[^\w\s]", "", media.series_name).replace(
                " ", "_"
            )
            fallback_path = (
                CACHE_DIR
                / f"{sanitized_series}_S{media.season_number:02d}E{media.episode_number:02d}.{target_lang}.srt"
            )
        else:
            # Unreachable, but needed for type checking
            fallback_path = CACHE_DIR / f"unknown.{target_lang}.srt"
        translated_subs.save(fallback_path, encoding="utf-8")
        console.print(f"[yellow]Saved to local cache instead: {fallback_path}[/yellow]")
        return fallback_path
