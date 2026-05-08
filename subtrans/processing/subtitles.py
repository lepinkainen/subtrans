"""Subtitle discovery and extraction from MKV files."""

import json
import subprocess
from pathlib import Path

import pysrt
from rich.table import Table

from ..core.cache import get_subtitle_cache_path
from ..core.models import Config, SubtitleTrack
from ..core.models import MediaItem
from ..core.utils import console


def find_mkv_file(media_path: str) -> Path | None:
    """
    Find the MKV file for a movie or episode.

    Args:
        media_path: Path to media file or directory

    Returns:
        Path to MKV file, or None if not found
    """
    media_dir = Path(media_path)
    if media_dir.is_file() and media_dir.suffix.lower() == ".mkv":
        return media_dir

    if media_dir.is_dir():
        mkv_files = list(media_dir.glob("*.mkv"))
        if mkv_files:
            # Return the largest MKV file (likely the main video file)
            return max(mkv_files, key=lambda p: p.stat().st_size)

    return None


def find_external_srt(media_path: str | Path, lang: str = "en") -> Path | None:
    """
    Find external SRT file for a movie or episode.

    Args:
        media_path: Path to media file or directory
        lang: Language code to search for (default: "en")

    Returns:
        Path to SRT file, or None if not found
    """
    media_dir = Path(media_path)
    if media_dir.is_file():
        media_dir = media_dir.parent

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
        matches = list(media_dir.glob(pattern))
        if matches:
            return matches[0]

    # Only use fallback pattern if no language-specific file exists
    # This returns None if there are only non-English files
    all_srts = list(media_dir.glob("*.srt"))
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
                    forced=props.get("forced_track", False),
                    sdh=props.get("flag_hearing_impaired", False),
                    entry_count=props.get("num_index_entries", 0),
                )
            )

    return tracks


def extract_subtitle_from_mkv(
    mkv_path: Path,
    track_id: int,
    output_path: Path,
    min_entries: int = 50,
    min_file_size: int = 2048,
) -> bool:
    """
    Extract a subtitle track from MKV file.

    Args:
        mkv_path: Path to MKV file
        track_id: Track ID to extract
        output_path: Where to save the extracted subtitle
        min_entries: Minimum subtitle entries for validation
        min_file_size: Minimum file size in bytes for validation

    Returns:
        True if extraction succeeded and validation passed, False otherwise
    """
    try:
        subprocess.run(
            ["mkvextract", "tracks", str(mkv_path), f"{track_id}:{output_path}"],
            capture_output=True,
            check=True,
        )

        # Validate the extracted file
        is_valid, entry_count, error_msg = validate_subtitle_file(
            output_path,
            min_entries=min_entries,
            min_file_size=min_file_size,
            context="extracted subtitle",
        )

        if not is_valid:
            console.print(f"[yellow]Warning: {error_msg}[/yellow]")
            console.print(
                "[yellow]Extraction completed but file appears corrupted[/yellow]"
            )
            # Delete the invalid cached file to force re-extraction next time
            if output_path.exists():
                output_path.unlink()
                console.print(
                    f"[yellow]Deleted invalid cached file: {output_path.name}[/yellow]"
                )
            return False

        console.print(
            f"[green]Validated: {entry_count} subtitle entries extracted[/green]"
        )
        return True

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error extracting subtitle: {e.stderr.decode()}[/red]")
        return False
    except FileNotFoundError:
        console.print("[red]mkvextract not found. Install mkvtoolnix.[/red]")
        return False


def validate_subtitle_file(
    srt_path: Path,
    min_entries: int = 50,
    min_file_size: int = 2048,
    context: str = "subtitle file",
) -> tuple[bool, int, str]:
    """
    Validate that a subtitle file meets minimum quality thresholds.

    Args:
        srt_path: Path to SRT file to validate
        min_entries: Minimum number of subtitle entries required
        min_file_size: Minimum file size in bytes
        context: Description of where this file came from (for error messages)

    Returns:
        Tuple of (is_valid, entry_count, error_message)
        - is_valid: True if file passes all validation checks
        - entry_count: Number of subtitle entries found (0 if file couldn't be parsed)
        - error_message: Empty string if valid, otherwise description of validation failure
    """
    # Check file exists
    if not srt_path.exists():
        return False, 0, f"{context} does not exist: {srt_path}"

    # Check minimum file size
    file_size = srt_path.stat().st_size
    if file_size < min_file_size:
        return (
            False,
            0,
            f"{context} is too small ({file_size} bytes, minimum {min_file_size} bytes). "
            "File may be corrupted or incomplete.",
        )

    # Parse and count subtitle entries
    try:
        subs = pysrt.open(srt_path, encoding="utf-8")
    except Exception:
        try:
            subs = pysrt.open(srt_path, encoding="latin-1")
        except Exception as e:
            return False, 0, f"Failed to parse {context}: {e}"

    entry_count = len(subs)

    # Check minimum entry count
    if entry_count == 0:
        return (
            False,
            0,
            f"{context} contains no subtitle entries - may be in unsupported format",
        )

    if entry_count < min_entries:
        return (
            False,
            entry_count,
            f"{context} has only {entry_count} entries (minimum {min_entries} expected). "
            "This seems suspiciously low for a typical movie. "
            "File may be corrupted, incomplete, or from a very short video.",
        )

    # All checks passed
    return True, entry_count, ""


def display_subtitle_tracks(
    tracks: list[SubtitleTrack],
    selected_track: SubtitleTrack | None,
    source_lang: str,
    show_all_languages: bool = False,
) -> None:
    """
    Display discovered subtitle tracks in a formatted table.

    Args:
        tracks: List of subtitle tracks to display
        selected_track: The automatically selected track (if any)
        source_lang: Source language code for context
        show_all_languages: Whether to show all languages or filter to source_lang
    """
    if not tracks:
        return

    # Create Rich table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Track", justify="center", style="cyan")
    table.add_column("Format", justify="center")
    table.add_column("Name", justify="left")

    if show_all_languages:
        table.add_column("Language", justify="center")

    table.add_column("Forced", justify="center")
    table.add_column("SDH", justify="center")
    table.add_column("Entries", justify="right")

    for track in tracks:
        # Determine if this is the selected track
        is_selected = selected_track and track.track_id == selected_track.track_id

        # Format codec for display
        # Handle multiple codec string formats from mkvmerge:
        # - S_TEXT/UTF8, S_TEXT/SRT (MKV Matroska)
        # - SubRip/SRT (some tools use this format)
        codec_display = (
            track.codec.replace("S_TEXT/", "")
            .replace("UTF8", "SRT")
            .replace("SubRip/", "")
        )

        # Check if codec is supported
        is_supported = codec_display in ["SRT"]

        # Build row data
        row_data = [
            str(track.track_id),
            codec_display,
            track.name or "(no name)",
        ]

        if show_all_languages:
            row_data.append(track.language or "und")

        row_data.extend(
            [
                "Yes" if track.forced else "No",
                "Yes" if track.sdh else "No",
                f"{track.entry_count:,}",
            ]
        )

        # Add selection indicator or warning
        if is_selected:
            row_data[-1] += " ← Selected"
            if track.forced:
                row_data[-1] += " (forced track)"
            elif track.sdh:
                row_data[-1] += " (SDH track)"
            else:
                row_data[-1] += " (full track)"
        elif not is_supported:
            row_data[-1] += " ⚠ Unsupported format"

        # Add row with appropriate styling
        if is_selected:
            table.add_row(*row_data, style="green")
        elif not is_supported:
            table.add_row(*row_data, style="dim yellow")
        else:
            table.add_row(*row_data)

    console.print(table)


def display_external_srt(srt_path: Path) -> tuple[int, int]:
    """
    Display external SRT file information.

    Args:
        srt_path: Path to the SRT file

    Returns:
        Tuple of (entry_count, file_size_bytes)
    """
    # Parse SRT to get entry count
    try:
        subtitles = pysrt.open(str(srt_path), encoding="utf-8")
        entry_count = len(subtitles)
    except Exception:
        # Fallback to latin-1 encoding
        try:
            subtitles = pysrt.open(str(srt_path), encoding="latin-1")
            entry_count = len(subtitles)
        except Exception:
            entry_count = 0

    # Get file size
    file_size = srt_path.stat().st_size
    file_size_kb = file_size / 1024

    console.print(f"[green]✓ Found external subtitle file: {srt_path.name}[/green]")
    console.print("  Format:   SRT")
    console.print(f"  Entries:  {entry_count:,}")
    console.print(f"  Size:     {file_size_kb:.1f} KB")

    return entry_count, file_size


def prompt_track_selection(
    tracks: list[SubtitleTrack],
    selected_track: SubtitleTrack | None,
    warnings: list[str],
    all_tracks: list[SubtitleTrack] | None = None,
) -> tuple[SubtitleTrack | None, bool]:
    """
    Prompt user to confirm or override track selection.

    Args:
        tracks: List of language-matching tracks being considered
        selected_track: The automatically selected track
        warnings: List of warning messages to display
        all_tracks: Complete list of all tracks (for 'list' command)

    Returns:
        tuple[SubtitleTrack | None, bool]: (selected_track, skip_requested)
        - (track, False): Use this track
        - (None, True): Skip this movie
    """
    # Display warnings
    for warning in warnings:
        console.print(f"[yellow]⚠ Warning: {warning}[/yellow]")

    if warnings:
        console.print()

    # Build prompt message based on context
    if selected_track:
        track_type = "full"
        if selected_track.forced:
            track_type = "forced"
        elif selected_track.sdh:
            track_type = "SDH"

        console.print(
            f"[green]✓ Auto-selected Track {selected_track.track_id}: "
            f"{track_type.capitalize()} subtitle track with {selected_track.entry_count:,} entries[/green]"
        )

    console.print()

    # Build valid track numbers for input validation
    valid_track_numbers = {str(t.track_id) for t in tracks}

    # Build prompt options
    track_range = sorted([t.track_id for t in tracks])
    if len(track_range) > 1:
        track_options = f"{min(track_range)}-{max(track_range)}"
    else:
        track_options = str(track_range[0]) if track_range else ""

    options_text = "[Y/n"
    if track_options:
        options_text += f"/{track_options}"
    if all_tracks:
        options_text += "/list"
    options_text += "]"

    console.print(f"Continue with this track? {options_text}")
    console.print(
        "  Y     - Use selected track"
        + (f" (Track {selected_track.track_id})" if selected_track else "")
    )
    console.print("  n     - Skip this movie")
    if track_options:
        console.print(f"  {track_options}   - Manually select different track number")
    if all_tracks:
        console.print("  list  - Show all tracks (including non-matching languages)")
    console.print()

    while True:
        try:
            response = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("[yellow]\nSkipping movie[/yellow]")
            return None, True

        # Handle empty response (default to Yes)
        if not response or response in ["y", "yes"]:
            return selected_track, False

        # Handle skip
        if response in ["n", "no", "skip"]:
            return None, True

        # Handle list all tracks
        if response == "list" and all_tracks:
            console.print(
                "\n[cyan]All subtitle tracks in file (any language):[/cyan]\n"
            )
            display_subtitle_tracks(
                all_tracks, selected_track, "", show_all_languages=True
            )
            console.print()
            continue

        # Handle manual track selection
        if response in valid_track_numbers:
            track_id = int(response)
            manually_selected = next(
                (t for t in tracks if t.track_id == track_id), None
            )
            if manually_selected:
                console.print(
                    f"[green]✓ Manually selected Track {track_id} "
                    f"({manually_selected.name or 'no name'} with {manually_selected.entry_count:,} entries)[/green]"
                )
                return manually_selected, False

        # Invalid input
        console.print(f"[red]Invalid input: '{response}'. Please try again.[/red]")


def get_source_subtitle(
    media: MediaItem,
    config: Config,
    source_lang: str = "en",
    min_entries: int = 50,
    min_file_size: int = 2048,
    skip_interactive: bool = False,
) -> tuple[Path | None, bool]:
    """
    Get source language subtitle for a movie or episode.

    Searches for subtitles in this order:
    1. External SRT file
    2. Embedded MKV subtitle (cached if extracted)

    Args:
        media: Movie or Episode object with path information
        config: Configuration object for interactive track selection
        source_lang: Source language code (ISO 639-1/2)
        min_entries: Minimum subtitle entries for validation
        min_file_size: Minimum file size in bytes for validation
        skip_interactive: Skip interactive prompts (used in Phase 2)

    Returns:
        Tuple of (path_to_srt, skip_requested)
    """
    # First, check for external SRT
    external_srt = find_external_srt(media.file_path, source_lang)
    if external_srt and external_srt.exists():
        # Display external SRT info if interactive mode is enabled
        if (
            config.interactive_track_selection
            and not config.auto_select_tracks
            and not skip_interactive
        ):
            entry_count, file_size = display_external_srt(external_srt)

            console.print()
            console.print("Continue with this subtitle? [Y/n/mkv]")
            console.print("  Y     - Use external SRT file")
            console.print("  n     - Skip this movie")
            console.print("  mkv   - Show embedded MKV tracks instead")
            console.print()

            while True:
                try:
                    response = input("> ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    console.print("[yellow]\nSkipping movie[/yellow]")
                    return None, True

                if not response or response in ["y", "yes"]:
                    return external_srt, False
                elif response in ["n", "no", "skip"]:
                    return None, True
                elif response == "mkv":
                    # Break out to check MKV tracks
                    break
                else:
                    console.print(
                        f"[red]Invalid input: '{response}'. Please try again.[/red]"
                    )
        else:
            console.print(
                f"[green]Found external subtitle: {external_srt.name}[/green]"
            )
            return external_srt, False

    # Check for embedded subtitles in MKV
    mkv_path = find_mkv_file(media.file_path)
    if not mkv_path:
        console.print("[yellow]No MKV file found[/yellow]")
        return None, False

    tracks = get_mkv_subtitle_tracks(mkv_path)
    if not tracks:
        console.print("[yellow]No text subtitle tracks found in MKV[/yellow]")
        return None, False

    # Find track matching source language
    # Priority: Full (non-SDH, non-forced) > Forced > SDH
    source_track = None
    matching_tracks = []

    for track in tracks:
        track_lang = track.language.lower()
        # Match 2-letter or 3-letter codes (e.g., "en", "eng", "english")
        if track_lang == source_lang or track_lang.startswith(source_lang):
            matching_tracks.append(track)

    if matching_tracks:
        # Separate tracks by type
        full_tracks = [t for t in matching_tracks if not t.forced and not t.sdh]
        forced_tracks = [t for t in matching_tracks if t.forced and not t.sdh]
        sdh_tracks = [t for t in matching_tracks if t.sdh]

        # Select best track with priority order: Full > Forced > SDH
        if full_tracks:
            # Best case: full subtitle track (non-SDH, non-forced)
            source_track = max(full_tracks, key=lambda t: t.entry_count)
        elif forced_tracks:
            # Acceptable: forced track (no full track available)
            source_track = max(forced_tracks, key=lambda t: t.entry_count)
        elif sdh_tracks:
            # Last resort: SDH track (includes sound effect descriptions)
            source_track = max(sdh_tracks, key=lambda t: t.entry_count)

        # Interactive track selection if enabled
        if (
            config.interactive_track_selection
            and not config.auto_select_tracks
            and not skip_interactive
        ):
            # Show discovered tracks
            console.print(
                f"\n[cyan]Discovered {source_lang.upper()} subtitle tracks:[/cyan]\n"
            )
            display_subtitle_tracks(matching_tracks, source_track, source_lang)
            console.print()

            # Build warnings list
            warnings = []
            if not full_tracks and forced_tracks:
                warnings.append("No full subtitle track available")
                warnings.append(
                    "Forced tracks only show subtitles for foreign language parts"
                )
            elif not full_tracks and not forced_tracks and sdh_tracks:
                warnings.append("Only SDH (hearing impaired) tracks available")
                warnings.append("SDH tracks contain sound effects and descriptions")
            if source_track and source_track.entry_count < 100:
                warnings.append(f"Low entry count ({source_track.entry_count} entries)")
            if len(full_tracks) > 1:
                warnings.append(
                    "Multiple full tracks - selected track with most entries"
                )

            # Check if only one track - skip prompt and auto-proceed
            if len(matching_tracks) == 1:
                # Single track - auto-proceed but still show selection message
                assert source_track is not None, (
                    "source_track should be set for single track"
                )

                track_type = "full"
                if source_track.forced:
                    track_type = "forced"
                elif source_track.sdh:
                    track_type = "SDH"

                console.print(
                    f"[green]✓ Using Track {source_track.track_id}: "
                    f"{track_type.capitalize()} subtitle track with {source_track.entry_count:,} entries[/green]"
                )
                # Don't call prompt_track_selection - just continue with source_track
            else:
                # Multiple tracks - prompt for user confirmation/selection
                selected, skip = prompt_track_selection(
                    matching_tracks, source_track, warnings, all_tracks=tracks
                )

                if skip:
                    return None, True

                source_track = selected
        else:
            # Non-interactive mode: just log the selection
            # source_track should be set by the logic above
            assert source_track is not None, (
                "source_track should be set when matching tracks exist"
            )

            if full_tracks:
                console.print(
                    f"[green]Selected full subtitle track: {source_track.name} "
                    f"({source_track.entry_count} entries)[/green]"
                )
            elif forced_tracks:
                console.print(
                    "[yellow]Warning: No full subtitle track available[/yellow]"
                )
                console.print(
                    f"[yellow]Using forced track: {source_track.name} "
                    f"({source_track.entry_count} entries)[/yellow]"
                )
            elif sdh_tracks:
                console.print(
                    "[yellow]Warning: Only SDH (hearing impaired) tracks available[/yellow]"
                )
                console.print(
                    "[yellow]SDH tracks contain sound effects - translations may include unnecessary text[/yellow]"
                )
                console.print(
                    f"[yellow]Using SDH track: {source_track.name} "
                    f"({source_track.entry_count} entries)[/yellow]"
                )

    # If no matching track, let user choose or use first track
    if not source_track:
        # Auto-select first track as fallback
        source_track = tracks[0]

        # Interactive track selection if enabled
        if (
            config.interactive_track_selection
            and not config.auto_select_tracks
            and not skip_interactive
        ):
            console.print(f"\n[yellow]No {source_lang} track found.[/yellow]\n")
            console.print("[cyan]Available tracks:[/cyan]\n")
            display_subtitle_tracks(
                tracks, source_track, source_lang, show_all_languages=True
            )
            console.print()

            warnings = ["No matching language track found"]
            if len(tracks) == 1:
                warnings.append(f"Using only available track: {source_track.language}")
            else:
                warnings.append(f"Using first track: {source_track.language}")

            selected, skip = prompt_track_selection(
                tracks, source_track, warnings, all_tracks=None
            )

            if skip:
                return None, True

            source_track = selected
        else:
            # Non-interactive mode: just log the fallback
            console.print(
                f"[yellow]No {source_lang} track found. Available tracks:[/yellow]"
            )
            for t in tracks:
                console.print(
                    f"  Track {t.track_id}: {t.language} - {t.name} ({t.codec})"
                )

            if len(tracks) == 1:
                console.print(
                    f"[yellow]Using only available track: {source_track.language}[/yellow]"
                )
            else:
                console.print(
                    f"[yellow]Using first track: {source_track.language}[/yellow]"
                )

    # At this point, source_track must be set (either from matching tracks or fallback)
    assert source_track is not None, (
        "source_track should be set by track selection logic"
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
        # Validate cached file before reusing
        is_valid, entry_count, error_msg = validate_subtitle_file(
            cached_srt,
            min_entries=min_entries,
            min_file_size=min_file_size,
            context="cached subtitle",
        )

        if is_valid:
            console.print("[green]Using cached subtitle[/green]")
            console.print(f"[green]Validated: {entry_count} entries[/green]")
            console.print(f"[dim]Cache: {cached_srt}[/dim]")
            return cached_srt, False
        else:
            # Cache is invalid - delete and re-extract
            console.print(f"[yellow]Cache validation failed: {error_msg}[/yellow]")
            console.print(
                "[yellow]Deleting corrupted cache and re-extracting...[/yellow]"
            )
            cached_srt.unlink()
            # Fall through to extraction below

    # Extract to cache
    console.print(
        f"[blue]Extracting track {source_track.track_id} from MKV to cache...[/blue]"
    )

    if extract_subtitle_from_mkv(
        mkv_path,
        source_track.track_id,
        cached_srt,
        min_entries=min_entries,
        min_file_size=min_file_size,
    ):
        console.print(f"[dim]Cached to {cached_srt}[/dim]")
        return cached_srt, False

    return None, False
