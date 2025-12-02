"""CLI entry point for subtrans application."""

import argparse
import os
import sys
from pathlib import Path

import pysrt
from openai import OpenAI
from rich.table import Table

from .core.config import load_config
from .core.models import Movie
from .core.utils import console
from .core.cache import load_cached_context, save_context_cache
from .integrations.bazarr import (
    get_wanted_movies,
    populate_movie_path,
    apply_path_mapping,
)
from .processing.subtitles import get_source_subtitle, find_mkv_file
from .processing.translator import analyze_subtitles, translate_subtitles_batch
from .processing.output import save_translated_subtitle


def select_movies_interactive(
    movies: list[Movie], target_lang: str = "fi"
) -> list[Movie]:
    """
    Interactive movie selection using rich.

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


def process_movie(
    movie: Movie,
    client: OpenAI,
    analysis_model: str = "gpt-4o",
    translation_model: str = "gpt-4o-mini",
    batch_size: int = 50,
    dry_run: bool = False,
    skip_analysis: bool = False,
    save_context: bool = True,
    path_mappings: list[tuple[str, str]] | None = None,
    extract_only: bool = False,
    source_lang: str = "en",
    target_lang: str = "fi",
) -> bool:
    """
    Process a single movie: get subtitle, analyze, translate, save.

    Args:
        movie: Movie to process
        client: OpenAI client
        analysis_model: OpenAI model for Pass 1 (context analysis)
        translation_model: OpenAI model for Pass 2 (translation)
        batch_size: Number of subtitles per API call
        dry_run: If True, skip translation (for testing)
        skip_analysis: Skip context analysis pass
        save_context: Save analysis context to cache
        path_mappings: Path mappings for NAS to local translation
        extract_only: If True, extract and cache subtitles only (no translation)
        source_lang: Source language code (ISO 639-1/2)
        target_lang: Target language code (ISO 639-1/2)

    Returns:
        True if processing succeeded, False otherwise
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
        console.print("[yellow]Dry run - skipping translation[/yellow]")
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
            )

            # Optionally save context for review/reuse in cache directory
            if save_context and context.raw_json:
                save_context_cache(context, movie.title, movie.year)

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
        console.print(f"[blue]Analysis model: {config.analysis_model}[/blue]")
        console.print(f"[blue]Translation model: {config.translation_model}[/blue]")
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
    selected = select_movies_interactive(movies, config.target_language)

    if not selected:
        console.print("[yellow]No movies selected.[/yellow]")
        sys.exit(0)

    # Fetch full details (including paths) for selected movies only
    console.print(f"[blue]Fetching paths for {len(selected)} selected movies...[/blue]")
    for movie in selected:
        populate_movie_path(movie, config.bazarr_url, config.bazarr_api_key)

    # Process each movie
    success_count = 0
    for movie in selected:
        if process_movie(
            movie,
            client,
            analysis_model=config.analysis_model,
            translation_model=config.translation_model,
            batch_size=config.batch_size,
            dry_run=config.dry_run,
            skip_analysis=config.skip_analysis,
            save_context=config.save_context,
            source_lang=config.source_language,
            target_lang=config.target_language,
            path_mappings=config.path_mappings if config.path_mappings else None,
            extract_only=args.extract_only,
        ):
            success_count += 1

    console.print(
        f"\n[bold]Completed: {success_count}/{len(selected)} movies processed[/bold]"
    )


if __name__ == "__main__":
    main()
