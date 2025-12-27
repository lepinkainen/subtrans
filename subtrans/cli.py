"""CLI entry point for subtrans application."""

import sys
import time

from openai import OpenAI
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
)

from .cli_args import parse_arguments
from .cli_ui import (
    display_token_stats,
    select_by_pattern,
    select_episodes_interactive,
    select_movies_interactive,
)
from .core.config import load_config
from .core.utils import console
from .integrations.bazarr import (
    get_wanted_movies,
    populate_movie_path,
    get_wanted_episodes,
    populate_episode_path,
)
from .workflows import (
    process_movie_phase1,
    process_movie_phase2,
    process_episode_phase1,
    process_episode_phase2,
)


def main():
    """Main entry point for subtrans CLI."""
    try:
        _main_impl()
    except KeyboardInterrupt:
        console.print("\n[yellow]Translation cancelled by user (Ctrl-C)[/yellow]")
        sys.exit(130)  # Standard exit code for SIGINT


def _main_impl():
    """Main implementation (wrapped by KeyboardInterrupt handler)."""
    args = parse_arguments()

    # Handle --stats option (doesn't require config)
    if args.stats:
        display_token_stats(args.movie)
        return

    # Validate mutually exclusive flags
    if args.select and (args.legacy_selection or args.force_fzf):
        console.print(
            "[yellow]Warning: --legacy-selection and --force-fzf "
            "are ignored when using --select[/yellow]"
        )

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

    # Get OpenAI API key from config (not needed for extract-only mode)
    api_key = config.openai_api_key

    if not api_key and not config.dry_run and not args.extract_only:
        console.print("[red]OpenAI API key not found[/red]")
        console.print(
            "[yellow]Set it in config.yml (openai.api_key) or OPENAI_API_KEY environment variable[/yellow]"
        )
        sys.exit(1)

    client = OpenAI(api_key=api_key) if api_key else None

    # Choose workflow based on --series flag
    if args.series:
        # Episode workflow
        console.print(
            f"[blue]Fetching episodes missing {config.target_language} subtitles from Bazarr...[/blue]"
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
            f"[green]Found {len(episodes)} episodes missing {config.target_language} subtitles[/green]"
        )

        # Note about data quality
        s00_count = sum(1 for ep in episodes if ep.season_number == 0)
        if s00_count > 0:
            console.print(
                f"[yellow]Warning: {s00_count} episodes show as S00E00 (may indicate Bazarr data sync issues)[/yellow]"
            )

        # Select episodes
        if args.select:
            selected = select_by_pattern(
                episodes, args.select, config.target_language, "episodes"
            )
        else:
            selected = select_episodes_interactive(
                episodes,
                config.target_language,
                legacy=args.legacy_selection,
                force_fzf=args.force_fzf,
            )

        if not selected:
            console.print("[yellow]No episodes selected.[/yellow]")
            sys.exit(0)

        # Fetch full details (including paths) for selected episodes only if not already present
        episodes_needing_paths = [ep for ep in selected if not ep.path]
        if episodes_needing_paths:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(
                    f"[blue]Fetching paths for {len(episodes_needing_paths)} episodes...",
                    total=len(episodes_needing_paths),
                )
                for episode in episodes_needing_paths:
                    populate_episode_path(
                        episode, config.bazarr_url, config.bazarr_api_key
                    )
                    progress.advance(task)
        else:
            console.print("[dim]All episodes already have paths from wanted API[/dim]")
    else:
        # Movie workflow
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

        # Note: Wanted API doesn't include year field, so years will show as (0) in selection UI
        # Years are populated for selected movies after selection
        if len(movies) > 100:
            console.print(
                "[dim]Note: Movie years will be populated after selection (showing 0 in UI for performance)[/dim]"
            )

        # Select movies
        if args.select:
            selected = select_by_pattern(
                movies, args.select, config.target_language, "movies"
            )
        else:
            selected = select_movies_interactive(
                movies,
                config.target_language,
                legacy=args.legacy_selection,
                force_fzf=args.force_fzf,
            )

        if not selected:
            console.print("[yellow]No movies selected.[/yellow]")
            sys.exit(0)

        # Fetch full details (including paths and years) for selected movies only
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

    # Handle extract-only mode separately (no translation phase)
    if args.extract_only:
        console.print("\n[bold blue]Extract-Only Mode: Caching Subtitles[/bold blue]")
        extract_count = 0
        total_selected = len(selected)

        if args.series:
            # Episode extract-only mode
            for idx, episode in enumerate(selected, start=1):
                if process_episode_phase1(
                    episode,
                    client,
                    config,
                    analysis_model=config.analysis_model,
                    dry_run=config.dry_run,
                    skip_analysis=True,
                    save_context=False,
                    path_mappings=config.path_mappings
                    if config.path_mappings
                    else None,
                    extract_only=True,
                    source_lang=config.source_language,
                    target_lang=config.target_language,
                    log_token_usage=config.log_token_usage,
                    service_tier=config.analysis_service_tier,
                    total_episodes=total_selected,
                    current_index=idx,
                    min_subtitle_count=config.min_subtitle_count,
                    min_subtitle_file_size=config.min_subtitle_file_size,
                    strict_validation=config.strict_validation,
                ):
                    extract_count += 1
        else:
            # Movie extract-only mode
            for idx, movie in enumerate(selected, start=1):
                if process_movie_phase1(
                    movie,
                    client,
                    config,
                    analysis_model=config.analysis_model,
                    dry_run=config.dry_run,
                    skip_analysis=True,
                    save_context=False,
                    path_mappings=config.path_mappings
                    if config.path_mappings
                    else None,
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

    # Phase 1: Context Analysis
    console.print("\n[bold blue]Phase 1: Context Analysis[/bold blue]")
    approved_items = []
    total_items = len(selected)

    if args.series:
        # Episode Phase 1
        for idx, episode in enumerate(selected, start=1):
            if process_episode_phase1(
                episode,
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
                total_episodes=total_items,
                current_index=idx,
                min_subtitle_count=config.min_subtitle_count,
                min_subtitle_file_size=config.min_subtitle_file_size,
                strict_validation=config.strict_validation,
            ):
                approved_items.append(episode)

        # Exit if no episodes approved
        if not approved_items:
            console.print("[yellow]No episodes approved for translation.[/yellow]")
            sys.exit(0)

        console.print(
            f"\n[green]{len(approved_items)}/{len(selected)} episodes approved for translation[/green]"
        )
    else:
        # Movie Phase 1
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
                total_movies=total_items,
                current_index=idx,
                min_subtitle_count=config.min_subtitle_count,
                min_subtitle_file_size=config.min_subtitle_file_size,
                strict_validation=config.strict_validation,
            ):
                approved_items.append(movie)

        # Exit if no movies approved
        if not approved_items:
            console.print("[yellow]No movies approved for translation.[/yellow]")
            sys.exit(0)

        console.print(
            f"\n[green]{len(approved_items)}/{len(selected)} movies approved for translation[/green]"
        )

    # Phase 2: Translation
    console.print("\n[bold blue]Phase 2: Translation[/bold blue]")
    success_count = 0
    total_approved = len(approved_items)

    # Start timing Phase 2
    phase2_start = time.time()

    if args.series:
        # Episode Phase 2
        for idx, episode in enumerate(approved_items, start=1):
            if process_episode_phase2(
                episode,
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
                total_episodes=total_approved,
                current_index=idx,
                min_subtitle_count=config.min_subtitle_count,
                min_subtitle_file_size=config.min_subtitle_file_size,
                strict_validation=config.strict_validation,
            ):
                success_count += 1

        media_type = "episodes"
    else:
        # Movie Phase 2
        for idx, movie in enumerate(approved_items, start=1):
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

        media_type = "movies"

    # Calculate elapsed time
    phase2_elapsed = time.time() - phase2_start
    hours = int(phase2_elapsed // 3600)
    minutes = int((phase2_elapsed % 3600) // 60)
    seconds = int(phase2_elapsed % 60)
    elapsed_str = f"{hours}:{minutes:02d}:{seconds:02d}"

    console.print(
        f"\n[bold]Completed: {success_count}/{len(approved_items)} {media_type} translated (elapsed: {elapsed_str})[/bold]"
    )


if __name__ == "__main__":
    main()
