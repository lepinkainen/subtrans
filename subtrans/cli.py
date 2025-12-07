"""CLI entry point for subtrans application."""

import argparse
import os
import sys
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
from .core.models import Movie
from .core.utils import console
from .core.cache import load_cached_context, save_context_cache, get_context_cache_path
from .integrations.bazarr import (
    get_wanted_movies,
    populate_movie_path,
    apply_path_mapping,
)
from .processing.subtitles import get_source_subtitle, find_mkv_file
from .processing.translator import analyze_subtitles, translate_subtitles_batch
from .processing.output import save_translated_subtitle
from .selection import select_movies_fzf


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


def process_movie_phase1(
    movie: Movie,
    client: OpenAI,
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

    Returns:
        True if user approved (or extract_only), False if cancelled/error
    """
    console.print(f"\n[bold blue]{'=' * 60}[/bold blue]")
    console.print(f"[bold blue]Processing: {movie.title} ({movie.year})[/bold blue]")

    # Apply path mapping
    original_path = movie.path
    if path_mappings:
        movie.path = apply_path_mapping(movie.path, path_mappings)

    console.print(f"Path: {movie.path}")
    if movie.path != original_path:
        console.print(f"[dim](Original: {original_path})[/dim]")

    # Get source language subtitle
    srt_path, is_temp = get_source_subtitle(movie, source_lang)

    if not srt_path:
        console.print(f"[red]Could not find {source_lang} subtitle[/red]")
        return False

    try:
        # Load subtitle file
        console.print(f"[blue]Loading subtitle: {srt_path}[/blue]")
        subs = pysrt.open(srt_path, encoding="utf-8")
    except Exception:
        try:
            subs = pysrt.open(srt_path, encoding="latin-1")
        except Exception as e:
            console.print(f"[red]Error loading subtitle: {e}[/red]")
            return False

    console.print(f"[green]Loaded {len(subs)} subtitle entries[/green]")

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

        # Always show context and wait for user approval in Phase 1
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

    Returns:
        True if translation succeeded, False otherwise
    """
    console.print(f"\n[bold blue]{'=' * 60}[/bold blue]")
    console.print(f"[bold blue]Translating: {movie.title} ({movie.year})[/bold blue]")

    # Apply path mapping
    original_path = movie.path
    if path_mappings:
        movie.path = apply_path_mapping(movie.path, path_mappings)

    console.print(f"Path: {movie.path}")
    if movie.path != original_path:
        console.print(f"[dim](Original: {original_path})[/dim]")

    # Get source language subtitle (should be in cache from Phase 1)
    srt_path, is_temp = get_source_subtitle(movie, source_lang)

    if not srt_path:
        console.print(f"[red]Could not find {source_lang} subtitle[/red]")
        return False

    try:
        # Load subtitle file
        console.print(f"[blue]Loading subtitle: {srt_path}[/blue]")
        subs = pysrt.open(srt_path, encoding="utf-8")
    except Exception:
        try:
            subs = pysrt.open(srt_path, encoding="latin-1")
        except Exception as e:
            console.print(f"[red]Error loading subtitle: {e}[/red]")
            return False

    console.print(f"[green]Loaded {len(subs)} subtitle entries[/green]")

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

    args = parser.parse_args()

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
        for movie in selected:
            if process_movie_phase1(
                movie,
                client,
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
            ):
                extract_count += 1
        console.print(
            f"\n[bold]Completed: {extract_count}/{len(selected)} subtitles cached[/bold]"
        )
        sys.exit(0)

    # Phase 1: Context Analysis for ALL movies
    console.print("\n[bold blue]Phase 1: Context Analysis[/bold blue]")
    approved_movies = []

    for movie in selected:
        if process_movie_phase1(
            movie,
            client,
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

    for movie in approved_movies:
        if process_movie_phase2(
            movie,
            client,
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
        ):
            success_count += 1

    console.print(
        f"\n[bold]Completed: {success_count}/{len(approved_movies)} movies translated[/bold]"
    )


if __name__ == "__main__":
    main()
