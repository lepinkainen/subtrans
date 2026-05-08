"""User interface and display functions for subtrans CLI."""

import fnmatch
import sys
from typing import cast

from rich.table import Table

from .core.media_types import is_episode, is_movie
from .core.models import Episode, Movie
from .core.token_logger import get_detailed_token_stats, get_pricing_age_info
from .core.utils import console
from .selection import select_episodes_fzf, select_movies_fzf


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


def select_episodes_legacy(
    episodes: list[Episode], target_lang: str = "fi"
) -> list[Episode]:
    """
    Legacy episode selection using numbered list.

    Args:
        episodes: List of available episodes
        target_lang: Target language code for display

    Returns:
        List of selected episodes
    """
    if not episodes:
        console.print(
            f"[yellow]No episodes missing {target_lang} subtitles found.[/yellow]"
        )
        return []

    # Display episodes in a table
    table = Table(title=f"Episodes Missing {target_lang.upper()} Subtitles")
    table.add_column("№", style="cyan", width=6)
    table.add_column("Series", style="green")
    table.add_column("Episode", style="yellow")
    table.add_column("Title", style="blue")
    table.add_column("Missing", style="red")

    for i, episode in enumerate(episodes, 1):
        table.add_row(
            str(i),
            episode.series_name,
            f"S{episode.season_number:02d}E{episode.episode_number:02d}",
            episode.episode_title,
            ", ".join(episode.missing_subtitles),
        )

    console.print(table)
    console.print()

    # Get user input
    while True:
        try:
            console.print(
                "[yellow]Enter episode numbers (comma-separated), 'all', or 'q' to quit:[/yellow]"
            )
            response = input("> ").strip().lower()

            if response == "q":
                return []

            if response == "all":
                return episodes

            # Parse comma-separated numbers
            selected_indices = []
            for num_str in response.split(","):
                num_str = num_str.strip()
                if num_str.isdigit():
                    idx = int(num_str) - 1
                    if 0 <= idx < len(episodes):
                        selected_indices.append(idx)
                    else:
                        console.print(
                            f"[red]Invalid number: {num_str} (out of range)[/red]"
                        )
                        selected_indices = []
                        break
                else:
                    console.print(f"[red]Invalid input: {num_str}[/red]")
                    selected_indices = []
                    break

            if selected_indices:
                return [episodes[i] for i in selected_indices]

        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Selection cancelled.[/yellow]")
            return []


def select_episodes_interactive(
    episodes: list[Episode],
    target_lang: str = "fi",
    legacy: bool = False,
    force_fzf: bool = False,
) -> list[Episode]:
    """
    Interactive episode selection using fzf-style or legacy interface.

    Args:
        episodes: List of available episodes
        target_lang: Target language code for display
        legacy: Whether to use the legacy numbered interface
        force_fzf: Force fzf-style interface even if terminal detection fails

    Returns:
        List of selected episodes
    """
    if legacy:
        return select_episodes_legacy(episodes, target_lang)
    return select_episodes_fzf(episodes, target_lang, force_fzf=force_fzf)


def select_by_pattern(
    media_items: list[Movie] | list[Episode],
    pattern: str,
    target_lang: str,
    media_type: str,
) -> list[Movie] | list[Episode]:
    """
    Select media items matching a glob pattern (non-interactive).

    Args:
        media_items: List of movies or episodes to filter
        pattern: Glob pattern (case-insensitive)
        target_lang: Target language code for display
        media_type: "movies" or "episodes" for display purposes

    Returns:
        List of matching media items

    Raises:
        SystemExit: If no matches found (fail fast)
    """
    pattern_lower = pattern.lower()
    matches = []

    for item in media_items:
        # Build search strings based on media type
        search_strings = []

        if is_movie(item):
            # For movies: check title, display_title, and combined display
            search_strings.append(item.title.lower())
            search_strings.append(item.display_title.lower())
            search_strings.append(
                f"{item.display_title} - {item.display_subtitle}".lower()
            )
        elif is_episode(item):
            # For episodes: check series_name, episode_title, display_title, and combined display
            search_strings.append(item.series_name.lower())
            if item.episode_title:
                search_strings.append(item.episode_title.lower())
            search_strings.append(item.display_title.lower())
            search_strings.append(
                f"{item.display_title} - {item.display_subtitle}".lower()
            )

        # Check if pattern matches any of the search strings
        if any(fnmatch.fnmatch(s, pattern_lower) for s in search_strings):
            matches.append(item)

    # If no matches, exit with error
    if not matches:
        console.print(f"[red]Error: No {media_type} matching pattern '{pattern}'[/red]")
        console.print(
            f"[dim]Searched {len(media_items)} {media_type} but found no matches.[/dim]"
        )
        sys.exit(1)

    # Display matched items in a table
    if media_type == "movies":
        table = Table(title=f"Selected {len(matches)} Movies Matching '{pattern}'")
        table.add_column("Title", style="green")
        table.add_column("Year", style="yellow")
        table.add_column("Missing", style="red")

        for item in matches:
            if is_movie(item):
                table.add_row(
                    item.title,
                    str(item.year),
                    ", ".join(item.missing_subtitles),
                )
    else:  # Episodes
        table = Table(title=f"Selected {len(matches)} Episodes Matching '{pattern}'")
        table.add_column("Series", style="green")
        table.add_column("Episode", style="yellow")
        table.add_column("Title", style="blue")
        table.add_column("Missing", style="red")

        for item in matches:
            if is_episode(item):
                table.add_row(
                    item.series_name,
                    f"S{item.season_number:02d}E{item.episode_number:02d}",
                    item.episode_title,
                    ", ".join(item.missing_subtitles),
                )

    console.print(table)
    console.print(
        f"[green]Pattern matched {len(matches)}/{len(media_items)} {media_type}[/green]"
    )

    # Type assertion: matches will be the same type as media_items
    return cast(list[Movie] | list[Episode], matches)
