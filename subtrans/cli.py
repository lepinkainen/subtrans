"""CLI entry point for subtrans application."""

import argparse
import os
import sys
import time
from pathlib import Path

import pysrt
from openai import OpenAI
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
)
from rich.table import Table

from .core.config import load_config
from .core.models import Config, Movie
from .core.utils import console
from .core.cache import load_cached_context, save_context_cache, get_context_cache_path
from .core.token_logger import get_detailed_token_stats, get_pricing_age_info
from .integrations.bazarr import (
    get_wanted_movies,
    populate_movie_path,
    apply_path_mapping,
)
from .processing.subtitles import get_source_subtitle, find_mkv_file
from .processing.translator import analyze_subtitles, translate_subtitles_batch
from .processing.output import check_translation_exists
from .processing.output import save_translated_subtitle
from .selection import select_movies_fzf


def display_token_stats(movie_filter: str | None = None) -> None:
    """
    Display detailed token usage statistics and costs.

    Args:
        movie_filter: Optional movie title filter
    """

    console.print("\n[bold blue]Token Usage Statistics[/bold blue]\n")

    stats = get_detailed_token_stats(movie_filter)

    if stats["total_operations"] == 0:
        console.print("[yellow]No token usage data found.[/yellow]")
        console.print(
            "[dim]Token usage is logged to ~/.cache/subtrans/token_usage.jsonl[/dim]"
        )
        return

    # Overall summary
    summary_table = Table(title="Overall Summary", show_header=False)
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", style="green")

    summary_table.add_row("Total Movies", str(stats["total_movies"]))
    summary_table.add_row("Total Operations", str(stats["total_operations"]))
    summary_table.add_row("Total Cost", f"${stats['total_cost']:.4f}")

    console.print(summary_table)
    console.print()

    # By Phase
    if stats["by_phase"]:
        phase_table = Table(title="By Phase")
        phase_table.add_column("Phase", style="cyan")
        phase_table.add_column("Operations", justify="right")
        phase_table.add_column("Input Tokens", justify="right", style="yellow")
        phase_table.add_column("Output Tokens", justify="right", style="yellow")
        phase_table.add_column("Cached Tokens", justify="right", style="green")
        phase_table.add_column("Cost", justify="right", style="green")

        for phase, data in sorted(stats["by_phase"].items()):
            phase_table.add_row(
                phase.capitalize(),
                str(data["operations"]),
                f"{data['input_tokens']:,}",
                f"{data['output_tokens']:,}",
                f"{data['cached_tokens']:,}",
                f"${data['cost']:.4f}",
            )

        console.print(phase_table)
        console.print()

    # By Model
    if stats["by_model"]:
        model_table = Table(title="By Model")
        model_table.add_column("Model", style="cyan")
        model_table.add_column("Operations", justify="right")
        model_table.add_column("Input Tokens", justify="right", style="yellow")
        model_table.add_column("Output Tokens", justify="right", style="yellow")
        model_table.add_column("Cached Tokens", justify="right", style="green")
        model_table.add_column("Cost", justify="right", style="green")

        for model, data in sorted(
            stats["by_model"].items(), key=lambda x: x[1]["cost"], reverse=True
        ):
            model_table.add_row(
                model,
                str(data["operations"]),
                f"{data['input_tokens']:,}",
                f"{data['output_tokens']:,}",
                f"{data['cached_tokens']:,}",
                f"${data['cost']:.4f}",
            )

        console.print(model_table)
        console.print()

    # By Movie (limit to top 20 most expensive)
    if stats["by_movie"]:
        movie_table = Table(title="By Movie (Top 20 Most Expensive)")
        movie_table.add_column("Movie", style="cyan")
        movie_table.add_column("Operations", justify="right")
        movie_table.add_column("Input Tokens", justify="right", style="yellow")
        movie_table.add_column("Output Tokens", justify="right", style="yellow")
        movie_table.add_column("Cached Tokens", justify="right", style="green")
        movie_table.add_column("Cost", justify="right", style="green")

        # Sort by cost, descending, and take top 20
        sorted_movies = sorted(
            stats["by_movie"].items(), key=lambda x: x[1]["cost"], reverse=True
        )[:20]

        for movie, data in sorted_movies:
            movie_table.add_row(
                movie,
                str(data["operations"]),
                f"{data['input_tokens']:,}",
                f"{data['output_tokens']:,}",
                f"{data['cached_tokens']:,}",
                f"${data['cost']:.4f}",
            )

        console.print(movie_table)

    console.print()

    # Display pricing age information
    pricing_info = get_pricing_age_info()
    if pricing_info["last_updated"]:
        days_old = pricing_info["days_old"]
        date_str = pricing_info["last_updated"]

        if days_old is not None:
            if days_old == 0:
                age_str = "today"
                style = "green"
            elif days_old == 1:
                age_str = "1 day old"
                style = "green"
            elif days_old < 30:
                age_str = f"{days_old} days old"
                style = "green"
            elif days_old < 90:
                age_str = f"{days_old} days old"
                style = "yellow"
            else:
                age_str = f"{days_old} days old"
                style = "red"

            console.print(
                f"[{style}]Using price information from {date_str} ({age_str})[/{style}]"
            )
        else:
            console.print(f"[dim]Using price information from {date_str}[/dim]")
    else:
        console.print(
            "[yellow]Warning: Pricing data does not include last_updated date[/yellow]"
        )

    console.print(
        "[dim]Cached tokens benefit from 90% discount. Prices shown are per-token actual costs.[/dim]"
    )


def select_movies_legacy(movies: list[Movie], target_lang: str = "fi") -> list[Movie]:
    """
    Legacy movie selection using numbered list.

    Args:
        movies: List of available movies
        target_lang: Target language code for display

    Returns:
        List of selected movies
    """
    if not movies:
        console.print(
            f"[yellow]No movies missing {target_lang} subtitles found.[/yellow]"
        )
        return []

    # Display table
    table = Table(title=f"Movies Missing {target_lang.upper()} Subtitles")
    table.add_column("#", style="cyan", width=4)
    table.add_column("Title", style="green")
    table.add_column("Year", style="yellow")
    table.add_column("Missing", style="red")

    for i, movie in enumerate(movies, 1):
        table.add_row(
            str(i),
            movie.title,
            str(movie.year),
            ", ".join(movie.missing_subtitles),
        )

    console.print(table)
    console.print()

    # Get selection
    console.print(
        "Enter movie numbers to translate (comma-separated, 'all', or 'q' to quit):"
    )
    selection = input("> ").strip().lower()

    if selection == "q":
        return []

    if selection == "all":
        return movies

    try:
        indices = [int(x.strip()) - 1 for x in selection.split(",")]
        return [movies[i] for i in indices if 0 <= i < len(movies)]
    except (ValueError, IndexError):
        console.print("[red]Invalid selection[/red]")
        return []


def select_movies_interactive(
    movies: list[Movie],
    target_lang: str = "fi",
    legacy: bool = False,
    force_fzf: bool = False,
) -> list[Movie]:
    """
    Interactive movie selection using fzf-style or legacy interface.

    Args:
        movies: List of available movies
        target_lang: Target language code for display
        legacy: Whether to use the legacy numbered interface
        force_fzf: Force fzf-style interface even if terminal detection fails

    Returns:
        List of selected movies
    """
    if legacy:
        return select_movies_legacy(movies, target_lang)
    return select_movies_fzf(movies, target_lang, force_fzf=force_fzf)


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

            from .core.utils import CACHE_DIR

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
        current_index: Current movie number (1-indexed)

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
        context = load_cached_context(movie.title, movie.year)

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
                save_context_cache(context, movie.title, movie.year)
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
            from rich.json import JSON
            from rich.panel import Panel

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
                # Edit the context JSON file
                import os
                import subprocess
                import sys

                context_path = get_context_cache_path(movie.title, movie.year)

                # Ensure the context is saved before editing
                if not context_path.exists():
                    save_context_cache(context, movie.title, movie.year)

                # Get the editor from environment or default
                editor = os.environ.get(
                    "EDITOR", "nano" if sys.platform != "win32" else "notepad"
                )

                try:
                    console.print(
                        f"[blue]Opening {context_path} with {editor}...[/blue]"
                    )
                    subprocess.run([editor, str(context_path)], check=True)

                    # Reload the context after editing
                    edited_context = load_cached_context(movie.title, movie.year)
                    if edited_context:
                        context = edited_context
                        console.print("[green]Context reloaded after editing[/green]")

                        # Show the edited context
                        json_content = JSON.from_data(context.raw_json, indent=2)
                        panel = Panel(
                            json_content,
                            title=f"Edited Context for {movie.title} ({movie.year})",
                            title_align="left",
                            border_style="green",
                        )
                        console.print(panel)

                        # Ask again what to do
                        console.print(
                            "\n[yellow]Approve edited context for translation? [Y/n][/yellow]"
                        )
                        response = input("> ").strip().lower()
                    else:
                        console.print(
                            "[red]Failed to reload edited context, using original[/red]"
                        )
                except subprocess.CalledProcessError:
                    console.print(f"[red]Failed to open editor '{editor}'[/red]")
                except FileNotFoundError:
                    console.print(
                        f"[red]Editor '{editor}' not found. Please set EDITOR environment variable.[/red]"
                    )
                except Exception as e:
                    console.print(f"[red]Error editing context: {e}[/red]")

            elif response == "d":
                # Show diff with cached context if it exists
                cached_context = load_cached_context(movie.title, movie.year)
                if cached_context and cached_context.raw_json != context.raw_json:
                    console.print(
                        "[blue]Showing differences between current and cached context:[/blue]"
                    )
                    # Simple diff display
                    from rich.columns import Columns

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
                        # Edit the context JSON file
                        import os
                        import subprocess
                        import sys

                        context_path = get_context_cache_path(movie.title, movie.year)

                        # Ensure the context is saved before editing
                        if not context_path.exists():
                            save_context_cache(context, movie.title, movie.year)

                        # Get the editor from environment or default
                        editor = os.environ.get(
                            "EDITOR",
                            "nano" if sys.platform != "win32" else "notepad",
                        )

                        try:
                            console.print(
                                f"[blue]Opening {context_path} with {editor}...[/blue]"
                            )
                            subprocess.run([editor, str(context_path)], check=True)

                            # Reload the context after editing
                            edited_context = load_cached_context(
                                movie.title, movie.year
                            )
                            if edited_context:
                                context = edited_context
                                console.print(
                                    "[green]Context reloaded after editing[/green]"
                                )

                                # Show the edited context
                                json_content = JSON.from_data(
                                    context.raw_json, indent=2
                                )
                                panel = Panel(
                                    json_content,
                                    title=f"Edited Context for {movie.title} ({movie.year})",
                                    title_align="left",
                                    border_style="green",
                                )
                                console.print(panel)

                                # Ask again what to do
                                console.print(
                                    "\n[yellow]Approve edited context for translation? [Y/n][/yellow]"
                                )
                                response = input("> ").strip().lower()
                            else:
                                console.print(
                                    "[red]Failed to reload edited context, using original[/red]"
                                )
                        except subprocess.CalledProcessError:
                            console.print(
                                f"[red]Failed to open editor '{editor}'[/red]"
                            )
                        except FileNotFoundError:
                            console.print(
                                f"[red]Editor '{editor}' not found. Please set EDITOR environment variable.[/red]"
                            )
                        except Exception as e:
                            console.print(f"[red]Error editing context: {e}[/red]")
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
                        # Edit the context JSON file
                        import os
                        import subprocess
                        import sys

                        context_path = get_context_cache_path(movie.title, movie.year)

                        # Ensure the context is saved before editing
                        if not context_path.exists():
                            save_context_cache(context, movie.title, movie.year)

                        # Get the editor from environment or default
                        editor = os.environ.get(
                            "EDITOR",
                            "nano" if sys.platform != "win32" else "notepad",
                        )

                        try:
                            console.print(
                                f"[blue]Opening {context_path} with {editor}...[/blue]"
                            )
                            subprocess.run([editor, str(context_path)], check=True)

                            # Reload the context after editing
                            edited_context = load_cached_context(
                                movie.title, movie.year
                            )
                            if edited_context:
                                context = edited_context
                                console.print(
                                    "[green]Context reloaded after editing[/green]"
                                )

                                # Show the edited context
                                json_content = JSON.from_data(
                                    context.raw_json, indent=2
                                )
                                panel = Panel(
                                    json_content,
                                    title=f"Edited Context for {movie.title} ({movie.year})",
                                    title_align="left",
                                    border_style="green",
                                )
                                console.print(panel)

                                # Ask again what to do
                                console.print(
                                    "\n[yellow]Approve edited context for translation? [Y/n][/yellow]"
                                )
                                response = input("> ").strip().lower()
                            else:
                                console.print(
                                    "[red]Failed to reload edited context, using original[/red]"
                                )
                        except subprocess.CalledProcessError:
                            console.print(
                                f"[red]Failed to open editor '{editor}'[/red]"
                            )
                        except FileNotFoundError:
                            console.print(
                                f"[red]Editor '{editor}' not found. Please set EDITOR environment variable.[/red]"
                            )
                        except Exception as e:
                            console.print(f"[red]Error editing context: {e}[/red]")

            if response and response not in ["y", "yes", ""]:
                console.print("[yellow]Context not approved - movie skipped.[/yellow]")
                return False

            # Context approved, save it if needed
            if save_context and context.raw_json:
                save_context_cache(context, movie.title, movie.year)
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
    exists, existing_path = check_translation_exists(
        movie.path, movie.title, movie.year, target_lang=target_lang
    )

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
    context = load_cached_context(movie.title, movie.year)
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
        movie.path,
        mkv_path,
        movie.title,
        movie.year,
        target_lang=target_lang,
    )
    console.print(
        f"[bold green]Saved {target_lang} subtitles: {output_path}[/bold green]"
    )

    # Note: No cleanup needed - cached subtitles are kept for reuse

    return True


def main():
    """Main entry point for subtrans CLI."""
    parser = argparse.ArgumentParser(
        description="Translate movie subtitles between languages using OpenAI"
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=Path("config.yml"),
        help="Path to config file (default: config.yml)",
    )
    parser.add_argument(
        "--extract-only",
        "-e",
        action="store_true",
        help="Extract and cache subtitles only (no translation)",
    )
    parser.add_argument(
        "--legacy-selection",
        action="store_true",
        help="Use legacy numbered selection instead of fzf-style interface",
    )
    parser.add_argument(
        "--force-fzf",
        action="store_true",
        help="Force fzf-style interface even if terminal detection fails",
    )
    parser.add_argument(
        "--stats",
        "-s",
        action="store_true",
        help="Display token usage statistics and costs, then exit",
    )
    parser.add_argument(
        "--movie",
        "-m",
        type=str,
        help="Filter statistics by movie title (use with --stats)",
    )

    args = parser.parse_args()

    # Handle --stats option (doesn't require config)
    if args.stats:
        display_token_stats(args.movie)
        return

    # Load configuration
    config = load_config(args.config)

    # Display config info
    console.print(f"[blue]Bazarr URL: {config.bazarr_url}[/blue]")
    console.print(
        f"[blue]Languages: {config.source_language} → {config.target_language}[/blue]"
    )

    if args.extract_only:
        console.print(
            "[yellow]Extract-only mode: Subtitles will be cached without translation[/yellow]"
        )
    else:
        console.print(
            f"[blue]Analysis model: {config.analysis_model} (tier: {config.analysis_service_tier})[/blue]"
        )
        console.print(
            f"[blue]Translation model: {config.translation_model} (tier: {config.translation_service_tier})[/blue]"
        )
        console.print(f"[blue]Batch size: {config.batch_size}[/blue]")

    if config.path_mappings:
        console.print("[blue]Path mappings:[/blue]")
        for from_path, to_path in config.path_mappings:
            console.print(f"  {from_path} -> {to_path}")

    # Get OpenAI API key from environment (not needed for extract-only mode)
    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key and not config.dry_run and not args.extract_only:
        console.print("[red]OPENAI_API_KEY environment variable not set[/red]")
        sys.exit(1)

    client = OpenAI(api_key=api_key) if api_key else None

    # Fetch wanted movies
    console.print(
        f"[blue]Fetching movies missing {config.target_language} subtitles from Bazarr...[/blue]"
    )
    movies = get_wanted_movies(
        config.bazarr_url,
        config.bazarr_api_key,
        source_lang=config.source_language,
        target_lang=config.target_language,
    )

    if not movies:
        console.print(
            f"[yellow]No movies found missing {config.target_language} subtitles.[/yellow]"
        )
        sys.exit(0)

    console.print(
        f"[green]Found {len(movies)} movies missing {config.target_language} subtitles[/green]"
    )

    # Select movies
    selected = select_movies_interactive(
        movies,
        config.target_language,
        legacy=args.legacy_selection,
        force_fzf=args.force_fzf,
    )

    if not selected:
        console.print("[yellow]No movies selected.[/yellow]")
        sys.exit(0)

    # Fetch full details (including paths) for selected movies only
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"[blue]Fetching paths for {len(selected)} movies...", total=len(selected)
        )
        for movie in selected:
            populate_movie_path(movie, config.bazarr_url, config.bazarr_api_key)
            progress.advance(task)

    # Handle extract-only mode separately (no translation phase)
    if args.extract_only:
        console.print("\n[bold blue]Extract-Only Mode: Caching Subtitles[/bold blue]")
        extract_count = 0
        total_selected = len(selected)
        for idx, movie in enumerate(selected, start=1):
            if process_movie_phase1(
                movie,
                client,
                config,
                analysis_model=config.analysis_model,
                dry_run=config.dry_run,
                skip_analysis=True,  # Skip analysis in extract-only mode
                save_context=False,
                path_mappings=config.path_mappings if config.path_mappings else None,
                extract_only=True,
                source_lang=config.source_language,
                target_lang=config.target_language,
                log_token_usage=config.log_token_usage,
                service_tier=config.analysis_service_tier,
                total_movies=total_selected,
                current_index=idx,
                min_subtitle_count=config.min_subtitle_count,
                min_subtitle_file_size=config.min_subtitle_file_size,
                strict_validation=config.strict_validation,
            ):
                extract_count += 1
        console.print(
            f"\n[bold]Completed: {extract_count}/{len(selected)} subtitles cached[/bold]"
        )
        sys.exit(0)

    # Phase 1: Context Analysis for ALL movies
    console.print("\n[bold blue]Phase 1: Context Analysis[/bold blue]")
    approved_movies = []
    total_movies = len(selected)

    for idx, movie in enumerate(selected, start=1):
        if process_movie_phase1(
            movie,
            client,
            config,
            analysis_model=config.analysis_model,
            dry_run=config.dry_run,
            skip_analysis=config.skip_analysis,
            save_context=config.save_context,
            path_mappings=config.path_mappings if config.path_mappings else None,
            extract_only=False,
            source_lang=config.source_language,
            target_lang=config.target_language,
            log_token_usage=config.log_token_usage,
            service_tier=config.analysis_service_tier,
            total_movies=total_movies,
            current_index=idx,
            min_subtitle_count=config.min_subtitle_count,
            min_subtitle_file_size=config.min_subtitle_file_size,
            strict_validation=config.strict_validation,
        ):
            approved_movies.append(movie)

    # Exit if no movies approved
    if not approved_movies:
        console.print("[yellow]No movies approved for translation.[/yellow]")
        sys.exit(0)

    console.print(
        f"\n[green]{len(approved_movies)}/{len(selected)} movies approved for translation[/green]"
    )

    # Phase 2: Translation for approved movies
    console.print("\n[bold blue]Phase 2: Translation[/bold blue]")
    success_count = 0
    total_approved = len(approved_movies)

    # Start timing Phase 2
    phase2_start = time.time()

    for idx, movie in enumerate(approved_movies, start=1):
        if process_movie_phase2(
            movie,
            client,
            config,
            translation_model=config.translation_model,
            batch_size=config.batch_size,
            dry_run=config.dry_run,
            path_mappings=config.path_mappings if config.path_mappings else None,
            source_lang=config.source_language,
            target_lang=config.target_language,
            validate_translation=config.validate_translation,
            min_translation_difference=config.min_translation_difference,
            log_token_usage=config.log_token_usage,
            service_tier=config.translation_service_tier,
            total_movies=total_approved,
            current_index=idx,
            min_subtitle_count=config.min_subtitle_count,
            min_subtitle_file_size=config.min_subtitle_file_size,
            strict_validation=config.strict_validation,
        ):
            success_count += 1

    # Calculate elapsed time
    phase2_elapsed = time.time() - phase2_start
    hours = int(phase2_elapsed // 3600)
    minutes = int((phase2_elapsed % 3600) // 60)
    seconds = int(phase2_elapsed % 60)
    elapsed_str = f"{hours}:{minutes:02d}:{seconds:02d}"

    console.print(
        f"\n[bold]Completed: {success_count}/{len(approved_movies)} movies translated (elapsed: {elapsed_str})[/bold]"
    )


if __name__ == "__main__":
    main()
