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
from .processing.subtitles import get_english_subtitle, find_mkv_file
from .processing.translator import analyze_subtitles, translate_subtitles_batch
from .processing.output import save_finnish_subtitle


def select_movies_interactive(movies: list[Movie]) -> list[Movie]:
    """
    Interactive movie selection using rich.

    Args:
        movies: List of available movies

    Returns:
        List of selected movies
    """
    if not movies:
        console.print("[yellow]No movies missing Finnish subtitles found.[/yellow]")
        return []

    # Display table
    table = Table(title="Movies Missing Finnish Subtitles")
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
    model: str = "gpt-4",
    batch_size: int = 50,
    dry_run: bool = False,
    skip_analysis: bool = False,
    save_context: bool = True,
    path_mappings: list[tuple[str, str]] | None = None,
) -> bool:
    """
    Process a single movie: get subtitle, analyze, translate, save.

    Args:
        movie: Movie to process
        client: OpenAI client
        model: OpenAI model to use
        batch_size: Number of subtitles per API call
        dry_run: If True, skip translation (for testing)
        skip_analysis: Skip context analysis pass
        save_context: Save analysis context to cache
        path_mappings: Path mappings for NAS to local translation

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

    # Get English subtitle
    srt_path, is_temp = get_english_subtitle(movie)

    if not srt_path:
        console.print("[red]Could not find English subtitle[/red]")
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

    # Pass 1: Analyze for context (unless skipped)
    context = None
    if not skip_analysis:
        # Check if we have a cached context first using cache module
        context = load_cached_context(movie.title, movie.year)

        if context is None:
            # No cached context, run analysis
            context = analyze_subtitles(subs, client, movie.title, model=model)

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
        model=model,
    )

    # Save translated subtitles
    mkv_path = find_mkv_file(movie.path)
    output_path = save_finnish_subtitle(
        translated,
        movie.path,
        mkv_path,
        movie.title,
        movie.year
    )
    console.print(f"[bold green]Saved Finnish subtitles: {output_path}[/bold green]")

    # Note: No cleanup needed - cached subtitles are kept for reuse

    return True


def main():
    """Main entry point for subtrans CLI."""
    parser = argparse.ArgumentParser(
        description="Translate movie subtitles from English to Finnish using OpenAI"
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=Path("config.yml"),
        help="Path to config file (default: config.yml)",
    )

    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # Display config info
    console.print(f"[blue]Bazarr URL: {config.bazarr_url}[/blue]")
    console.print(f"[blue]Model: {config.openai_model}[/blue]")
    console.print(f"[blue]Batch size: {config.batch_size}[/blue]")

    if config.path_mappings:
        console.print("[blue]Path mappings:[/blue]")
        for from_path, to_path in config.path_mappings:
            console.print(f"  {from_path} -> {to_path}")

    # Get OpenAI API key from environment
    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key and not config.dry_run:
        console.print(
            "[red]OPENAI_API_KEY environment variable not set[/red]"
        )
        sys.exit(1)

    client = OpenAI(api_key=api_key) if api_key else None

    # Fetch wanted movies
    console.print(
        "[blue]Fetching movies missing Finnish subtitles from Bazarr...[/blue]"
    )
    movies = get_wanted_movies(config.bazarr_url, config.bazarr_api_key)

    if not movies:
        console.print("[yellow]No movies found missing Finnish subtitles.[/yellow]")
        sys.exit(0)

    console.print(
        f"[green]Found {len(movies)} movies missing Finnish subtitles[/green]"
    )

    # Select movies
    selected = select_movies_interactive(movies)

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
            model=config.openai_model,
            batch_size=config.batch_size,
            dry_run=config.dry_run,
            skip_analysis=config.skip_analysis,
            save_context=config.save_context,
            path_mappings=config.path_mappings if config.path_mappings else None,
        ):
            success_count += 1

    console.print(
        f"\n[bold]Completed: {success_count}/{len(selected)} movies processed[/bold]"
    )


if __name__ == "__main__":
    main()
