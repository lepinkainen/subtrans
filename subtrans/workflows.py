"""Workflow functions for subtitle extraction and translation phases."""

import os
import subprocess
from pathlib import Path

import pysrt
from openai import OpenAI
from rich.json import JSON
from rich.panel import Panel
from rich.columns import Columns

from .core.cache import (
    get_context_cache_path,
    load_cached_context,
    save_context_cache,
)
from .core.models import Config, Episode, Movie
from .core.utils import CACHE_DIR, console
from .integrations.bazarr import apply_path_mapping
from .processing.output import check_translation_exists, save_translated_subtitle
from .processing.subtitles import find_mkv_file, get_source_subtitle
from .processing.translator import analyze_subtitles, translate_subtitles_batch


def load_and_validate_subtitle(
    srt_path: Path,
    min_subtitle_count: int,
    strict_validation: bool,
) -> tuple[pysrt.SubRipFile | None, int]:
    """
    Load and validate subtitle file with encoding fallback and user prompts.

    Handles:
    - UTF-8/latin-1 encoding fallback
    - Entry count validation
    - Interactive prompts for strict validation mode
    - Cache management (deletion for re-extraction)

    Args:
        srt_path: Path to SRT file to load
        min_subtitle_count: Minimum entries expected (typically 50 for movies)
        strict_validation: If True, prompt user on validation failures

    Returns:
        Tuple of (loaded_subtitles, entry_count)
        - loaded_subtitles: SubRipFile object or None if loading failed/user skipped
        - entry_count: Number of entries found (0 if failed)

    User can choose to:
    - Continue anyway (overlook validation warning)
    - Re-extract from MKV (delete cache, return None)
    - Skip movie (return None)
    """
    try:
        # Load subtitle file
        console.print(f"[blue]Loading subtitle: {srt_path}[/blue]")
        subs = pysrt.open(srt_path, encoding="utf-8")
    except Exception:
        try:
            subs = pysrt.open(srt_path, encoding="latin-1")
        except Exception as e:
            console.print(f"[red]Error loading subtitle: {e}[/red]")
            return None, 0

    entry_count = len(subs)
    console.print(f"[green]Loaded {entry_count} subtitle entries[/green]")

    # Enhanced validation with user override option
    if entry_count == 0:
        console.print(
            "[red]Error: No subtitle entries found - file may be in unsupported format[/red]"
        )
        console.print("[yellow]Supported format: SRT (.srt files)[/yellow]")
        return None, 0

    if entry_count < min_subtitle_count:
        warning_msg = (
            f"[yellow]Warning: Only {entry_count} subtitle entries found "
            f"(expected at least {min_subtitle_count} for typical movies)[/yellow]"
        )
        console.print(warning_msg)
        console.print(
            "[yellow]This could indicate a corrupted cache, incomplete extraction, "
            "or a very short video (trailer, short film, etc.)[/yellow]"
        )

        if strict_validation:
            # Strict mode: ask user before proceeding
            console.print(
                "[yellow]Strict validation is enabled. You can:[/yellow]\n"
                "  [cyan]c[/cyan] - Continue anyway (might waste API credits)\n"
                "  [cyan]r[/cyan] - Re-extract from MKV (delete cache and retry)\n"
                "  [cyan]s[/cyan] - Skip this movie\n"
            )

            while True:
                choice = input("Your choice [c/r/s]: ").strip().lower()
                if choice == "s":
                    console.print("[yellow]Skipping movie[/yellow]")
                    return None, 0
                elif choice == "r":
                    console.print("[blue]Re-extracting subtitle...[/blue]")
                    # Delete cache if it exists
                    if srt_path.exists() and CACHE_DIR in srt_path.parents:
                        srt_path.unlink()
                        console.print(
                            f"[yellow]Deleted cache: {srt_path.name}[/yellow]"
                        )
                    console.print(
                        "[yellow]Please re-run the program to re-extract[/yellow]"
                    )
                    return None, 0
                elif choice == "c":
                    console.print(
                        "[yellow]Continuing with low entry count (user override)[/yellow]"
                    )
                    break
                else:
                    console.print("[red]Invalid choice. Enter c, r, or s[/red]")
        else:
            # Permissive mode: just warn
            console.print(
                "[yellow]Continuing anyway (strict_validation is disabled)[/yellow]"
            )

    return subs, entry_count


def process_movie_phase1(
    movie: Movie,
    client: OpenAI,
    config: Config,
    analysis_model: str = "gpt-4o",
    dry_run: bool = False,
    skip_analysis: bool = False,
    save_context: bool = True,
    path_mappings: list[tuple[str, str]] | None = None,
    extract_only: bool = False,
    source_lang: str = "en",
    target_lang: str = "fi",
    log_token_usage: bool = True,
    service_tier: str = "auto",
    total_movies: int = 1,
    current_index: int = 1,
    min_subtitle_count: int = 50,
    min_subtitle_file_size: int = 2048,
    strict_validation: bool = True,
) -> bool:
    """
    Phase 1: Extract subtitle, analyze context, display for user review.

    Args:
        movie: Movie to process
        client: OpenAI client
        config: Config object for interactive selection settings
        analysis_model: OpenAI model for context analysis
        dry_run: If True, skip context analysis (for testing)
        skip_analysis: Skip context analysis pass
        save_context: Save analysis context to cache
        path_mappings: Path mappings for NAS to local translation
        extract_only: If True, extract and cache subtitles only (no analysis)
        source_lang: Source language code (ISO 639-1/2)
        target_lang: Target language code (ISO 639-1/2)
        log_token_usage: Log API token usage for cost tracking
        service_tier: OpenAI API service tier ("auto", "flex", "default", "priority")
        total_movies: Total number of movies being processed
        current_index: Current movie number (1-indexed)
        min_subtitle_count: Minimum entries for valid subtitle
        min_subtitle_file_size: Minimum file size for valid subtitle
        strict_validation: Hard error vs warning on validation failure

    Returns:
        True if user approved (or extract_only), False if cancelled/error
    """
    console.print(f"\n[bold blue]{'=' * 60}[/bold blue]")
    progress_indicator = (
        f" ({current_index}/{total_movies})" if total_movies > 1 else ""
    )
    console.print(
        f"[bold blue]Processing: {movie.title} ({movie.year}){progress_indicator}[/bold blue]"
    )

    # Apply path mapping
    original_path = movie.path
    if path_mappings:
        movie.path = apply_path_mapping(movie.path, path_mappings)

    console.print(f"Path: {movie.path}")
    if movie.path != original_path:
        console.print(f"[dim](Original: {original_path})[/dim]")

    # Get source language subtitle
    srt_path, skip_requested = get_source_subtitle(
        movie,
        config,
        source_lang,
        min_entries=min_subtitle_count,
        min_file_size=min_subtitle_file_size,
    )

    if skip_requested:
        console.print(f"[yellow]Skipped {movie.title}[/yellow]")
        return False

    if not srt_path:
        console.print(f"[red]Could not find {source_lang} subtitle[/red]")
        return False

    # Load and validate subtitle file
    subs, entry_count = load_and_validate_subtitle(
        srt_path, min_subtitle_count, strict_validation
    )

    if subs is None:
        return False

    if extract_only:
        console.print(
            "[yellow]Extract-only mode - subtitle cached successfully[/yellow]"
        )
        return True

    if dry_run:
        console.print("[yellow]Dry run - skipping analysis[/yellow]")
        return True

    # Pass 1: Analyze for context (unless skipped)
    context = None
    if not skip_analysis:
        # Check if we have a cached context first using cache module
        context = load_cached_context(movie)

        if context is None:
            # No cached context, run analysis
            context = analyze_subtitles(
                subs,
                client,
                movie.title,
                model=analysis_model,
                source_lang=source_lang,
                target_lang=target_lang,
                movie_year=movie.year,
                log_token_usage=log_token_usage,
                service_tier=service_tier,
            )

            # Optionally save context for review/reuse in cache directory
            if save_context and context.raw_json:
                save_context_cache(context, movie)
        else:
            console.print("[blue]Using cached context from previous analysis[/blue]")

            # Auto-accept cached contexts when batch processing
            if total_movies > 1:
                console.print(
                    "[green]Auto-accepting cached context (batch mode)[/green]"
                )
                return True  # Auto-approved

        # Show context and wait for user approval (single movie OR fresh context)
        if context and context.raw_json:
            console.print(
                "\n[bold blue]Translation Context (Pass 1 Analysis):[/bold blue]"
            )

            # Create a pretty JSON display
            json_content = JSON.from_data(context.raw_json, indent=2)
            panel = Panel(
                json_content,
                title=f"Context for {movie.title} ({movie.year})",
                title_align="left",
                border_style="blue",
            )
            console.print(panel)

            # Wait for user confirmation
            console.print(
                "\n[yellow]Approve this context for translation? [Y/n/e/d][/yellow]"
            )
            console.print(
                "[dim]Y=yes, n=no, e=edit context JSON, d=diff with cached[/dim]"
            )
            response = input("> ").strip().lower()

            if response == "e":
                response = _handle_context_edit(movie, context)
            elif response == "d":
                response = _handle_context_diff(movie, context)

            if response and response not in ["y", "yes", ""]:
                console.print("[yellow]Context not approved - movie skipped.[/yellow]")
                return False

            # Context approved, save it if needed
            if save_context and context.raw_json:
                save_context_cache(context, movie)
                console.print("[green]Context saved to cache[/green]")

    return True


def process_movie_phase2(
    movie: Movie,
    client: OpenAI,
    config: Config,
    translation_model: str = "gpt-4o-mini",
    batch_size: int = 50,
    dry_run: bool = False,
    path_mappings: list[tuple[str, str]] | None = None,
    source_lang: str = "en",
    target_lang: str = "fi",
    validate_translation: bool = True,
    min_translation_difference: float = 0.8,
    log_token_usage: bool = True,
    service_tier: str = "flex",
    total_movies: int = 1,
    current_index: int = 1,
    min_subtitle_count: int = 50,
    min_subtitle_file_size: int = 2048,
    strict_validation: bool = True,
) -> bool:
    """
    Phase 2: Load cached context, translate subtitles, save output.

    Args:
        movie: Movie to process
        client: OpenAI client
        config: Config object for interactive selection settings
        translation_model: OpenAI model for translation
        batch_size: Number of subtitles per API call
        dry_run: If True, skip translation (for testing)
        path_mappings: Path mappings for NAS to local translation
        source_lang: Source language code (ISO 639-1/2)
        target_lang: Target language code (ISO 639-1/2)
        validate_translation: Whether to validate translation quality
        min_translation_difference: Minimum difference ratio (0.0-1.0)
        log_token_usage: Log API token usage for cost tracking
        service_tier: OpenAI API service tier ("auto", "flex", "default", "priority")
        total_movies: Total number of movies being processed
        current_index: Current movie number (1-indexed)
        min_subtitle_count: Minimum entries for valid subtitle
        min_subtitle_file_size: Minimum file size for valid subtitle
        strict_validation: Hard error vs warning on validation failure

    Returns:
        True if translation succeeded, False otherwise
    """
    console.print(f"\n[bold blue]{'=' * 60}[/bold blue]")
    progress_indicator = (
        f" ({current_index}/{total_movies})" if total_movies > 1 else ""
    )
    console.print(
        f"[bold blue]Translating: {movie.title} ({movie.year}){progress_indicator}[/bold blue]"
    )

    # Apply path mapping
    original_path = movie.path
    if path_mappings:
        movie.path = apply_path_mapping(movie.path, path_mappings)

    console.print(f"Path: {movie.path}")
    if movie.path != original_path:
        console.print(f"[dim](Original: {original_path})[/dim]")

    # Check if translation already exists
    exists, existing_path = check_translation_exists(movie, target_lang=target_lang)

    if exists:
        console.print(f"[yellow]Translation already exists: {existing_path}[/yellow]")
        console.print("[yellow]Skipping re-translation[/yellow]")
        return True  # Success - movie already translated

    # Get source language subtitle (should be in cache from Phase 1)
    srt_path, skip_requested = get_source_subtitle(
        movie,
        config,
        source_lang,
        min_entries=min_subtitle_count,
        min_file_size=min_subtitle_file_size,
        skip_interactive=True,  # Skip prompts in Phase 2 - use cached subtitle
    )

    if skip_requested:
        console.print(f"[yellow]Skipped {movie.title}[/yellow]")
        return False

    if not srt_path:
        console.print(f"[red]Could not find {source_lang} subtitle[/red]")
        return False

    # Load and validate subtitle file
    subs, entry_count = load_and_validate_subtitle(
        srt_path, min_subtitle_count, strict_validation
    )

    if subs is None:
        return False

    if dry_run:
        console.print("[yellow]Dry run - skipping translation[/yellow]")
        return True

    # Load cached context from Phase 1
    context = load_cached_context(movie)
    if context:
        console.print("[blue]Using cached context from Phase 1[/blue]")
    else:
        console.print(
            "[yellow]Warning: No cached context found, translating without context[/yellow]"
        )

    # Pass 2: Translate with context
    translated = translate_subtitles_batch(
        subs,
        client,
        movie.title,
        context=context,
        batch_size=batch_size,
        model=translation_model,
        source_lang=source_lang,
        target_lang=target_lang,
        validate_translation=validate_translation,
        min_translation_difference=min_translation_difference,
        movie_year=movie.year,
        log_token_usage=log_token_usage,
        service_tier=service_tier,
    )

    # Save translated subtitles
    mkv_path = find_mkv_file(movie.path)
    output_path = save_translated_subtitle(
        translated,
        movie,
        mkv_path,
        target_lang=target_lang,
    )
    console.print(
        f"[bold green]Saved {target_lang} subtitles: {output_path}[/bold green]"
    )

    # Note: No cleanup needed - cached subtitles are kept for reuse

    return True


def process_episode_phase1(
    episode: Episode,
    client: OpenAI,
    config: Config,
    analysis_model: str = "gpt-4o",
    dry_run: bool = False,
    skip_analysis: bool = False,
    save_context: bool = True,
    path_mappings: list[tuple[str, str]] | None = None,
    extract_only: bool = False,
    source_lang: str = "en",
    target_lang: str = "fi",
    log_token_usage: bool = True,
    service_tier: str = "auto",
    total_episodes: int = 1,
    current_index: int = 1,
    min_subtitle_count: int = 50,
    min_subtitle_file_size: int = 2048,
    strict_validation: bool = True,
) -> bool:
    """
    Phase 1: Extract subtitle, analyze context, display for user review.

    Args:
        episode: Episode to process
        client: OpenAI client
        config: Config object for interactive selection settings
        analysis_model: OpenAI model for context analysis
        dry_run: If True, skip context analysis (for testing)
        skip_analysis: Skip context analysis pass
        save_context: Save analysis context to cache
        path_mappings: Path mappings for NAS to local translation
        extract_only: If True, extract and cache subtitles only (no analysis)
        source_lang: Source language code (ISO 639-1/2)
        target_lang: Target language code (ISO 639-1/2)
        log_token_usage: Log API token usage for cost tracking
        service_tier: OpenAI API service tier ("auto", "flex", "default", "priority")
        total_episodes: Total number of episodes being processed
        current_index: Current episode number (1-indexed)
        min_subtitle_count: Minimum entries for valid subtitle
        min_subtitle_file_size: Minimum file size for valid subtitle
        strict_validation: Hard error vs warning on validation failure

    Returns:
        True if user approved (or extract_only), False if cancelled/error
    """
    console.print(f"\n[bold blue]{'=' * 60}[/bold blue]")
    progress_indicator = (
        f" ({current_index}/{total_episodes})" if total_episodes > 1 else ""
    )
    console.print(
        f"[bold blue]Processing: {episode.display_title}{progress_indicator}[/bold blue]"
    )
    console.print(f"[dim]{episode.display_subtitle}[/dim]")

    # Apply path mapping
    original_path = episode.path
    if path_mappings:
        episode.path = apply_path_mapping(episode.path, path_mappings)

    console.print(f"Path: {episode.path}")
    if episode.path != original_path:
        console.print(f"[dim](Original: {original_path})[/dim]")

    # Get source language subtitle
    srt_path, skip_requested = get_source_subtitle(
        episode,
        config,
        source_lang,
        min_entries=min_subtitle_count,
        min_file_size=min_subtitle_file_size,
    )

    if skip_requested:
        console.print(f"[yellow]Skipped {episode.display_title}[/yellow]")
        return False

    if not srt_path:
        console.print(f"[red]Could not find {source_lang} subtitle[/red]")
        return False

    # Load and validate subtitle file
    subs, entry_count = load_and_validate_subtitle(
        srt_path, min_subtitle_count, strict_validation
    )

    if subs is None:
        return False

    if extract_only:
        console.print(
            "[yellow]Extract-only mode - subtitle cached successfully[/yellow]"
        )
        return True

    if dry_run:
        console.print("[yellow]Dry run - skipping analysis[/yellow]")
        return True

    # Pass 1: Analyze for context (unless skipped)
    context = None
    if not skip_analysis:
        # Check if we have a cached context first using cache module
        context = load_cached_context(episode)

        if context is None:
            # No cached context, run analysis
            context = analyze_subtitles(
                subs,
                client,
                episode.display_title,
                model=analysis_model,
                source_lang=source_lang,
                target_lang=target_lang,
                movie_year=episode.series_year,
                log_token_usage=log_token_usage,
                service_tier=service_tier,
            )

            # Optionally save context for review/reuse in cache directory
            if save_context and context.raw_json:
                save_context_cache(context, episode)
        else:
            console.print("[blue]Using cached context from previous analysis[/blue]")

            # Auto-accept cached contexts when batch processing
            if total_episodes > 1:
                console.print(
                    "[green]Auto-accepting cached context (batch mode)[/green]"
                )
                return True  # Auto-approved

        # Show context and wait for user approval (single episode OR fresh context)
        if context and context.raw_json:
            console.print(
                "\n[bold blue]Translation Context (Pass 1 Analysis):[/bold blue]"
            )

            # Create a pretty JSON display
            json_content = JSON.from_data(context.raw_json, indent=2)
            panel = Panel(
                json_content,
                title=f"Context for {episode.display_title}",
                title_align="left",
                border_style="blue",
            )
            console.print(panel)

            # Wait for user confirmation
            console.print(
                "\n[yellow]Approve this context for translation? [Y/n/e/d][/yellow]"
            )
            console.print(
                "[dim]Y=yes, n=no, e=edit context JSON, d=diff with cached[/dim]"
            )
            response = input("> ").strip().lower()

            if response == "e":
                response = _handle_context_edit(episode, context)
            elif response == "d":
                response = _handle_context_diff(episode, context)

            if response and response not in ["y", "yes", ""]:
                console.print(
                    "[yellow]Context not approved - episode skipped.[/yellow]"
                )
                return False

            # Context approved, save it if needed
            if save_context and context.raw_json:
                save_context_cache(context, episode)
                console.print("[green]Context saved to cache[/green]")

    return True


def process_episode_phase2(
    episode: Episode,
    client: OpenAI,
    config: Config,
    translation_model: str = "gpt-4o-mini",
    batch_size: int = 50,
    dry_run: bool = False,
    path_mappings: list[tuple[str, str]] | None = None,
    source_lang: str = "en",
    target_lang: str = "fi",
    validate_translation: bool = True,
    min_translation_difference: float = 0.8,
    log_token_usage: bool = True,
    service_tier: str = "flex",
    total_episodes: int = 1,
    current_index: int = 1,
    min_subtitle_count: int = 50,
    min_subtitle_file_size: int = 2048,
    strict_validation: bool = True,
) -> bool:
    """
    Phase 2: Load cached context, translate subtitles, save output.

    Args:
        episode: Episode to process
        client: OpenAI client
        config: Config object for interactive selection settings
        translation_model: OpenAI model for translation
        batch_size: Number of subtitles per API call
        dry_run: If True, skip translation (for testing)
        path_mappings: Path mappings for NAS to local translation
        source_lang: Source language code (ISO 639-1/2)
        target_lang: Target language code (ISO 639-1/2)
        validate_translation: Whether to validate translation quality
        min_translation_difference: Minimum difference ratio (0.0-1.0)
        log_token_usage: Log API token usage for cost tracking
        service_tier: OpenAI API service tier ("auto", "flex", "default", "priority")
        total_episodes: Total number of episodes being processed
        current_index: Current episode number (1-indexed)
        min_subtitle_count: Minimum entries for valid subtitle
        min_subtitle_file_size: Minimum file size for valid subtitle
        strict_validation: Hard error vs warning on validation failure

    Returns:
        True if translation succeeded, False otherwise
    """
    console.print(f"\n[bold blue]{'=' * 60}[/bold blue]")
    progress_indicator = (
        f" ({current_index}/{total_episodes})" if total_episodes > 1 else ""
    )
    console.print(
        f"[bold blue]Translating: {episode.display_title}{progress_indicator}[/bold blue]"
    )
    console.print(f"[dim]{episode.display_subtitle}[/dim]")

    # Apply path mapping
    original_path = episode.path
    if path_mappings:
        episode.path = apply_path_mapping(episode.path, path_mappings)

    console.print(f"Path: {episode.path}")
    if episode.path != original_path:
        console.print(f"[dim](Original: {original_path})[/dim]")

    # Check if translation already exists
    exists, existing_path = check_translation_exists(episode, target_lang=target_lang)

    if exists:
        console.print(f"[yellow]Translation already exists: {existing_path}[/yellow]")
        console.print("[yellow]Skipping re-translation[/yellow]")
        return True  # Success - episode already translated

    # Get source language subtitle (should be in cache from Phase 1)
    srt_path, skip_requested = get_source_subtitle(
        episode,
        config,
        source_lang,
        min_entries=min_subtitle_count,
        min_file_size=min_subtitle_file_size,
        skip_interactive=True,  # Skip prompts in Phase 2 - use cached subtitle
    )

    if skip_requested:
        console.print(f"[yellow]Skipped {episode.display_title}[/yellow]")
        return False

    if not srt_path:
        console.print(f"[red]Could not find {source_lang} subtitle[/red]")
        return False

    # Load and validate subtitle file
    subs, entry_count = load_and_validate_subtitle(
        srt_path, min_subtitle_count, strict_validation
    )

    if subs is None:
        return False

    if dry_run:
        console.print("[yellow]Dry run - skipping translation[/yellow]")
        return True

    # Load cached context from Phase 1
    context = load_cached_context(episode)
    if context:
        console.print("[blue]Using cached context from Phase 1[/blue]")
    else:
        console.print(
            "[yellow]Warning: No cached context found, translating without context[/yellow]"
        )

    # Pass 2: Translate with context
    translated = translate_subtitles_batch(
        subs,
        client,
        episode.display_title,
        context=context,
        batch_size=batch_size,
        model=translation_model,
        source_lang=source_lang,
        target_lang=target_lang,
        validate_translation=validate_translation,
        min_translation_difference=min_translation_difference,
        movie_year=episode.series_year,
        log_token_usage=log_token_usage,
        service_tier=service_tier,
    )

    # Save translated subtitles
    mkv_path = find_mkv_file(episode.path)
    output_path = save_translated_subtitle(
        translated,
        episode,
        mkv_path,
        target_lang=target_lang,
    )
    console.print(
        f"[bold green]Saved {target_lang} subtitles: {output_path}[/bold green]"
    )

    # Note: No cleanup needed - cached subtitles are kept for reuse

    return True


def _handle_context_edit(media_item: Movie | Episode, context) -> str:
    """
    Handle context editing workflow.

    Args:
        media_item: Movie or Episode being processed
        context: Current translation context

    Returns:
        User response after editing ('y', 'n', or '')
    """
    context_path = get_context_cache_path(media_item)

    # Ensure the context is saved before editing
    if not context_path.exists():
        save_context_cache(context, media_item)

    # Get the editor from environment or default
    import sys

    editor = os.environ.get("EDITOR", "nano" if sys.platform != "win32" else "notepad")

    try:
        console.print(f"[blue]Opening {context_path} with {editor}...[/blue]")
        subprocess.run([editor, str(context_path)], check=True)

        # Reload the context after editing
        edited_context = load_cached_context(media_item)
        if edited_context:
            context = edited_context
            console.print("[green]Context reloaded after editing[/green]")

            # Show the edited context
            json_content = JSON.from_data(context.raw_json, indent=2)
            title = (
                f"Edited Context for {media_item.title} ({media_item.year})"
                if isinstance(media_item, Movie)
                else f"Edited Context for {media_item.display_title}"
            )
            panel = Panel(
                json_content,
                title=title,
                title_align="left",
                border_style="green",
            )
            console.print(panel)

            # Ask again what to do
            console.print(
                "\n[yellow]Approve edited context for translation? [Y/n][/yellow]"
            )
            return input("> ").strip().lower()
        else:
            console.print("[red]Failed to reload edited context, using original[/red]")
            return "n"
    except subprocess.CalledProcessError:
        console.print(f"[red]Failed to open editor '{editor}'[/red]")
        return "n"
    except FileNotFoundError:
        console.print(
            f"[red]Editor '{editor}' not found. Please set EDITOR environment variable.[/red]"
        )
        return "n"
    except Exception as e:
        console.print(f"[red]Error editing context: {e}[/red]")
        return "n"


def _handle_context_diff(media_item: Movie | Episode, context) -> str:
    """
    Handle context diff display workflow.

    Args:
        media_item: Movie or Episode being processed
        context: Current translation context

    Returns:
        User response after viewing diff ('y', 'n', 'e', or '')
    """
    cached_context = load_cached_context(media_item)
    if cached_context and cached_context.raw_json != context.raw_json:
        console.print(
            "[blue]Showing differences between current and cached context:[/blue]"
        )
        # Simple diff display
        cached_panel = Panel(
            JSON.from_data(cached_context.raw_json, indent=2),
            title="Cached Context",
            border_style="red",
        )

        current_panel = Panel(
            JSON.from_data(context.raw_json, indent=2),
            title="Current Context",
            border_style="green",
        )

        console.print(Columns([cached_panel, current_panel], equal=True))

        # Ask again what to do
        console.print(
            "\n[yellow]Approve this context for translation? [Y/n/e][/yellow]"
        )
        console.print("[dim]Y=yes, n=no, e=edit current context[/dim]")
        response = input("> ").strip().lower()

        # Process the response again (but only handle 'e' here to avoid recursion)
        if response == "e":
            return _handle_context_edit(media_item, context)
        return response
    else:
        console.print(
            "[yellow]No differences found or no cached context available[/yellow]"
        )
        # Ask again what to do
        console.print(
            "\n[yellow]Approve this context for translation? [Y/n/e][/yellow]"
        )
        console.print("[dim]Y=yes, n=no, e=edit current context[/dim]")
        response = input("> ").strip().lower()

        if response == "e":
            return _handle_context_edit(media_item, context)
        return response
