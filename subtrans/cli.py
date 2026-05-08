"""CLI entry point for subtrans application."""

import sys
import time
from collections.abc import Callable, Sequence
from typing import cast

from openai import OpenAI
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from .cli_args import parse_arguments
from .cli_ui import (
    display_token_stats,
    select_by_pattern,
    select_episodes_interactive,
    select_movies_interactive,
)
from .core.config import load_config
from .core.models import Config, Episode, MediaItem, Movie
from .core.utils import console
from .integrations.bazarr import (
    get_wanted_episodes,
    get_wanted_movies,
    populate_episode_paths_bulk,
    populate_movie_path,
)
from .workflows import process_phase1, process_phase2


def _run_phase(
    items: Sequence[MediaItem],
    phase_fn: Callable[..., bool],
    *,
    extract_only: bool = False,
) -> list[MediaItem]:
    """Iterate ``phase_fn`` over ``items``; return the ones it accepted."""
    accepted: list[MediaItem] = []
    total = len(items)
    for idx, item in enumerate(items, start=1):
        ok = (
            phase_fn(item, current_index=idx, total=total, extract_only=extract_only)
            if extract_only
            else phase_fn(item, current_index=idx, total=total)
        )
        if ok:
            accepted.append(item)
    return accepted


def _format_elapsed(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}"


def main():
    """Main entry point for subtrans CLI."""
    try:
        _main_impl()
    except KeyboardInterrupt:
        console.print("\n[yellow]Translation cancelled by user (Ctrl-C)[/yellow]")
        sys.exit(130)


def _main_impl():
    args = parse_arguments()

    if args.stats:
        display_token_stats(args.movie)
        return

    if args.select and (args.legacy_selection or args.force_fzf):
        console.print(
            "[yellow]Warning: --legacy-selection and --force-fzf "
            "are ignored when using --select[/yellow]"
        )

    config = load_config(args.config)

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
            f"[blue]Analysis model: {config.analysis_model} "
            f"(tier: {config.analysis_service_tier})[/blue]"
        )
        console.print(
            f"[blue]Translation model: {config.translation_model} "
            f"(tier: {config.translation_service_tier})[/blue]"
        )
        console.print(f"[blue]Batch size: {config.batch_size}[/blue]")

    if config.path_mappings:
        console.print("[blue]Path mappings:[/blue]")
        for from_path, to_path in config.path_mappings:
            console.print(f"  {from_path} -> {to_path}")

    api_key = config.openai_api_key

    if not api_key and not config.dry_run and not args.extract_only:
        console.print("[red]OpenAI API key not found[/red]")
        console.print(
            "[yellow]Set it in config.yml (openai.api_key) or "
            "OPENAI_API_KEY environment variable[/yellow]"
        )
        sys.exit(1)

    client: OpenAI | None = OpenAI(api_key=api_key) if api_key else None

    selected: Sequence[MediaItem]
    media_label: str
    if args.series:
        selected = _gather_episodes(args, config)
        media_label = "episodes"
    else:
        selected = _gather_movies(args, config)
        media_label = "movies"

    if args.extract_only:
        console.print("\n[bold blue]Extract-Only Mode: Caching Subtitles[/bold blue]")
        accepted = _run_phase(
            selected,
            lambda item, **kw: process_phase1(item, client, config, **kw),
            extract_only=True,
        )
        console.print(
            f"\n[bold]Completed: {len(accepted)}/{len(selected)} subtitles cached[/bold]"
        )
        sys.exit(0)

    console.print("\n[bold blue]Phase 1: Context Analysis[/bold blue]")
    approved = _run_phase(
        selected,
        lambda item, **kw: process_phase1(item, client, config, **kw),
    )

    if not approved:
        console.print(f"[yellow]No {media_label} approved for translation.[/yellow]")
        sys.exit(0)

    console.print(
        f"\n[green]{len(approved)}/{len(selected)} {media_label} "
        "approved for translation[/green]"
    )

    if client is None:
        console.print("[red]OpenAI client not configured; cannot run Phase 2.[/red]")
        sys.exit(1)

    console.print("\n[bold blue]Phase 2: Translation[/bold blue]")
    phase2_start = time.time()
    success = _run_phase(
        approved,
        lambda item, **kw: process_phase2(item, client, config, **kw),
    )
    elapsed = _format_elapsed(time.time() - phase2_start)

    console.print(
        f"\n[bold]Completed: {len(success)}/{len(approved)} {media_label} "
        f"translated (elapsed: {elapsed})[/bold]"
    )


def _select_episodes(episodes: list[Episode], args, config: Config) -> list[Episode]:
    if args.select:
        return cast(
            list[Episode],
            select_by_pattern(
                episodes, args.select, config.target_language, "episodes"
            ),
        )
    return select_episodes_interactive(
        episodes,
        config.target_language,
        legacy=args.legacy_selection,
        force_fzf=args.force_fzf,
    )


def _select_movies(movies: list[Movie], args, config: Config) -> list[Movie]:
    if args.select:
        return cast(
            list[Movie],
            select_by_pattern(movies, args.select, config.target_language, "movies"),
        )
    return select_movies_interactive(
        movies,
        config.target_language,
        legacy=args.legacy_selection,
        force_fzf=args.force_fzf,
    )


def _gather_episodes(args, config: Config) -> list[Episode]:
    """Fetch wanted episodes, run selection UI, populate paths in bulk."""
    console.print(
        f"[blue]Fetching episodes missing {config.target_language} "
        "subtitles from Bazarr...[/blue]"
    )
    episodes = get_wanted_episodes(
        config.bazarr_url,
        config.bazarr_api_key,
        source_lang=config.source_language,
        target_lang=config.target_language,
    )

    if not episodes:
        console.print(
            f"[yellow]No episodes found missing {config.target_language} subtitles.[/yellow]"
        )
        sys.exit(0)

    console.print(
        f"[green]Found {len(episodes)} episodes missing "
        f"{config.target_language} subtitles[/green]"
    )

    s00_count = sum(1 for ep in episodes if ep.season_number == 0)
    if s00_count > 0:
        console.print(
            f"[yellow]Warning: {s00_count} episodes show as S00E00 "
            "(may indicate Bazarr data sync issues)[/yellow]"
        )

    selected = _select_episodes(episodes, args, config)
    if not selected:
        console.print("[yellow]No episodes selected.[/yellow]")
        sys.exit(0)

    needs_paths = [ep for ep in selected if not ep.path]
    if needs_paths:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                f"[blue]Fetching paths for {len(needs_paths)} episodes...",
                total=1,
            )
            populate_episode_paths_bulk(
                needs_paths, config.bazarr_url, config.bazarr_api_key
            )
            progress.update(task, completed=1)
    else:
        console.print("[dim]All episodes already have paths from wanted API[/dim]")

    return selected


def _gather_movies(args, config: Config) -> list[Movie]:
    """Fetch wanted movies, run selection UI, populate paths/years."""
    console.print(
        f"[blue]Fetching movies missing {config.target_language} "
        "subtitles from Bazarr...[/blue]"
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
        f"[green]Found {len(movies)} movies missing "
        f"{config.target_language} subtitles[/green]"
    )

    if len(movies) > 100:
        # The wanted API does not return year, so the selection UI shows (0)
        # until populate_movie_path runs after selection.
        console.print(
            "[dim]Note: Movie years will be populated after selection "
            "(showing 0 in UI for performance)[/dim]"
        )

    selected = _select_movies(movies, args, config)
    if not selected:
        console.print("[yellow]No movies selected.[/yellow]")
        sys.exit(0)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"[blue]Fetching details for {len(selected)} movies...",
            total=len(selected),
        )
        for movie in selected:
            populate_movie_path(movie, config.bazarr_url, config.bazarr_api_key)
            progress.advance(task)

    return selected


if __name__ == "__main__":
    main()
