"""File output operations for translated subtitles."""

from pathlib import Path

import pysrt

from ..core.utils import console, CACHE_DIR


def save_finnish_subtitle(
    translated_subs: pysrt.SubRipFile,
    movie_path: str,
    mkv_path: Path | None = None,
    movie_title: str = "movie",
    movie_year: int = 0,
) -> Path:
    """
    Save the translated subtitles with Finnish language suffix.

    Args:
        translated_subs: Translated subtitle file
        movie_path: Original movie path
        mkv_path: Path to MKV file (if known)
        movie_title: Movie title for fallback naming
        movie_year: Movie year for fallback naming

    Returns:
        Path where subtitle was saved
    """
    if mkv_path:
        # Use MKV filename as base
        output_path = mkv_path.parent / f"{mkv_path.stem}.fi.srt"
    else:
        # Use movie directory
        movie_dir = Path(movie_path)
        if movie_dir.is_file():
            output_path = movie_dir.parent / f"{movie_dir.stem}.fi.srt"
        else:
            # Find any video file
            for ext in [".mkv", ".mp4", ".avi"]:
                videos = list(movie_dir.glob(f"*{ext}"))
                if videos:
                    output_path = videos[0].parent / f"{videos[0].stem}.fi.srt"
                    break
            else:
                output_path = movie_dir / "movie.fi.srt"

    # Try to save to the movie directory
    try:
        translated_subs.save(output_path, encoding="utf-8")
        return output_path
    except (PermissionError, OSError) as e:
        # If we can't write to NAS, save to local cache instead
        console.print(
            f"[yellow]Cannot write to {output_path}: {e}[/yellow]"
        )
        safe_title = "".join(c for c in f"{movie_title}_{movie_year}" if c.isalnum() or c in (' ', '_')).rstrip()
        safe_title = safe_title.replace(' ', '_')
        fallback_path = CACHE_DIR / f"{safe_title}.fi.srt"
        translated_subs.save(fallback_path, encoding="utf-8")
        console.print(f"[yellow]Saved to local cache instead: {fallback_path}[/yellow]")
        return fallback_path
