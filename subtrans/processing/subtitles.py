"""Subtitle discovery and extraction from MKV files."""

import json
import subprocess
from pathlib import Path

from ..core.cache import get_subtitle_cache_path
from ..core.models import Movie, SubtitleTrack
from ..core.utils import console


def find_mkv_file(movie_path: str) -> Path | None:
    """
    Find the MKV file in the movie directory.

    Args:
        movie_path: Path to movie file or directory

    Returns:
        Path to MKV file, or None if not found
    """
    movie_dir = Path(movie_path)
    if movie_dir.is_file() and movie_dir.suffix.lower() == ".mkv":
        return movie_dir

    if movie_dir.is_dir():
        mkv_files = list(movie_dir.glob("*.mkv"))
        if mkv_files:
            # Return the largest MKV file (likely the main movie)
            return max(mkv_files, key=lambda p: p.stat().st_size)

    return None


def find_external_srt(movie_path: str | Path, lang: str = "en") -> Path | None:
    """
    Find external SRT file for the movie.

    Args:
        movie_path: Path to movie file or directory
        lang: Language code to search for (default: "en")

    Returns:
        Path to SRT file, or None if found
    """
    movie_dir = Path(movie_path)
    if movie_dir.is_file():
        movie_dir = movie_dir.parent

    # Look for subtitle patterns with language code first
    lang_patterns = [
        f"*.{lang}.srt",  # movie.en.srt
        f"*.{lang.upper()}.srt",  # movie.EN.srt
    ]

    # More specific patterns for English language
    if lang.lower() == "en":
        lang_patterns.extend(
            [
                "*.[Ee]ng*.srt",  # movie.eng.srt, movie.english.srt
                "*.[Ee]nglish*.srt",  # movie.english.srt
            ]
        )

    # Check language-specific patterns first
    for pattern in lang_patterns:
        matches = list(movie_dir.glob(pattern))
        if matches:
            return matches[0]

    # Only use fallback pattern if no language-specific file exists
    # This returns None if there are only non-English files
    all_srts = list(movie_dir.glob("*.srt"))
    if all_srts:
        # If there are SRT files but none match the language, return None
        # to trigger checking for embedded subtitles
        return None

    return None


def get_mkv_subtitle_tracks(mkv_path: Path) -> list[SubtitleTrack]:
    """
    Get list of subtitle tracks from MKV file using mkvmerge.

    Args:
        mkv_path: Path to MKV file

    Returns:
        List of SubtitleTrack objects
    """
    try:
        result = subprocess.run(
            ["mkvmerge", "-J", str(mkv_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        info = json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error reading MKV info: {e.stderr}[/red]")
        return []
    except FileNotFoundError:
        console.print("[red]mkvmerge not found. Install mkvtoolnix.[/red]")
        return []

    tracks = []
    for track in info.get("tracks", []):
        if track.get("type") == "subtitles":
            props = track.get("properties", {})
            codec = track.get("codec", "")

            # Skip image-based subtitles (PGS, VobSub)
            if codec.lower() in ("hdmv_pgs_subtitle", "vobsub", "dvd_subtitle"):
                continue

            # Skip non-SRT text formats (ASS, SSA, WebVTT, etc.)
            # MKV codec strings: S_TEXT/ASS, S_TEXT/SSA, S_TEXT/WEBVTT
            # Only support: S_TEXT/UTF8, S_TEXT/SRT (plain SRT format)
            codec_upper = codec.upper()
            if (
                "S_TEXT/ASS" in codec_upper
                or "S_TEXT/SSA" in codec_upper
                or "S_TEXT/WEBVTT" in codec_upper
            ):
                continue

            tracks.append(
                SubtitleTrack(
                    track_id=track.get("id"),
                    language=props.get("language", "und"),
                    name=props.get("track_name", ""),
                    codec=codec,
                )
            )

    return tracks


def extract_subtitle_from_mkv(mkv_path: Path, track_id: int, output_path: Path) -> bool:
    """
    Extract a subtitle track from MKV file.

    Args:
        mkv_path: Path to MKV file
        track_id: Track ID to extract
        output_path: Where to save the extracted subtitle

    Returns:
        True if extraction succeeded, False otherwise
    """
    try:
        subprocess.run(
            ["mkvextract", "tracks", str(mkv_path), f"{track_id}:{output_path}"],
            capture_output=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error extracting subtitle: {e.stderr.decode()}[/red]")
        return False
    except FileNotFoundError:
        console.print("[red]mkvextract not found. Install mkvtoolnix.[/red]")
        return False


def get_source_subtitle(
    movie: Movie, source_lang: str = "en"
) -> tuple[Path | None, bool]:
    """
    Get source language subtitle for a movie.

    Searches for subtitles in this order:
    1. External SRT file
    2. Embedded MKV subtitle (cached if extracted)

    Args:
        movie: Movie object with path information
        source_lang: Source language code (ISO 639-1/2)

    Returns:
        Tuple of (path_to_srt, is_temporary)
    """
    # First, check for external SRT
    external_srt = find_external_srt(movie.path, source_lang)
    if external_srt and external_srt.exists():
        console.print(f"[green]Found external subtitle: {external_srt.name}[/green]")
        return external_srt, False

    # Check for embedded subtitles in MKV
    mkv_path = find_mkv_file(movie.path)
    if not mkv_path:
        console.print("[yellow]No MKV file found[/yellow]")
        return None, False

    tracks = get_mkv_subtitle_tracks(mkv_path)
    if not tracks:
        console.print("[yellow]No text subtitle tracks found in MKV[/yellow]")
        return None, False

    # Find track matching source language
    source_track = None
    for track in tracks:
        track_lang = track.language.lower()
        # Match 2-letter or 3-letter codes (e.g., "en", "eng", "english")
        if track_lang == source_lang or track_lang.startswith(source_lang):
            source_track = track
            break

    # If no matching track, let user choose or use first track
    if not source_track:
        console.print(
            f"[yellow]No {source_lang} track found. Available tracks:[/yellow]"
        )
        for t in tracks:
            console.print(f"  Track {t.track_id}: {t.language} - {t.name} ({t.codec})")

        if len(tracks) == 1:
            source_track = tracks[0]
            console.print(
                f"[yellow]Using only available track: {source_track.language}[/yellow]"
            )
        else:
            # Use first text track as fallback
            source_track = tracks[0]
            console.print(
                f"[yellow]Using first track: {source_track.language}[/yellow]"
            )

    # Validate codec is supported (SRT format only)
    codec_upper = source_track.codec.upper()
    if (
        "S_TEXT/ASS" in codec_upper
        or "S_TEXT/SSA" in codec_upper
        or "S_TEXT/WEBVTT" in codec_upper
    ):
        console.print(
            f"[yellow]Found subtitle track but format not supported: {source_track.codec}[/yellow]"
        )
        console.print(
            "[yellow]Only SRT format subtitles are currently supported[/yellow]"
        )
        return None, False

    # Check cache first - use cache module function
    cached_srt = get_subtitle_cache_path(mkv_path, source_track.track_id)

    if cached_srt.exists():
        console.print("[green]Using cached subtitle[/green]")
        console.print(f"[dim]Cache: {cached_srt}[/dim]")
        return cached_srt, False  # Not temporary, it's cached

    # Extract to cache
    console.print(
        f"[blue]Extracting track {source_track.track_id} from MKV to cache...[/blue]"
    )

    if extract_subtitle_from_mkv(mkv_path, source_track.track_id, cached_srt):
        console.print(f"[dim]Cached to {cached_srt}[/dim]")
        return cached_srt, False  # Not temporary, it's cached

    return None, False
