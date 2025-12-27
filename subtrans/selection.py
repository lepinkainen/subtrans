"""Fzf-style media selection interface using prompt-toolkit."""

import sys
from typing import cast

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style
from rich.table import Table

from .core.models import Movie, Episode
from .core.media_types import MediaType
from .core.utils import console


def is_interactive_terminal() -> bool:
    """Check if we're running in an interactive terminal."""
    return sys.stdin.isatty() and sys.stdout.isatty()


class MultiSelectControl(FormattedTextControl):
    """Custom control for multi-select with fuzzy search."""

    def __init__(
        self,
        media_items: list[MediaType],
        media_type_label: str = "movies",
    ):
        self.media_items = media_items
        self.media_type_label = media_type_label  # "movies" or "episodes"
        self.filtered_indices = list(range(len(media_items)))
        self.selected_indices: set[int] = set()
        self.cursor_position = 0
        self.search_text = ""

        # Pre-compute formatted media strings for faster filtering
        self.media_strings = []
        for item in media_items:
            item_str = f"{item.display_title} - {item.display_subtitle}"
            self.media_strings.append(item_str.lower())

        # Initialize with callable that generates content dynamically
        super().__init__(self._get_formatted_content)

    def _get_header_content(self) -> FormattedText:
        """Get the header content (search and instructions)."""
        content = []

        # Search line
        content.append(("class:search", f"Search: {self.search_text}"))
        content.append(("", "\n"))

        # Instructions
        content.append(
            (
                "class:instruction",
                "Type to filter | ↑/↓ j/k: move | Space: toggle | Ctrl-a: all | Enter: confirm | q: quit",
            )
        )
        content.append(("", "\n"))

        # Summary line
        selected_count = len(self.selected_indices)
        visible_count = len(self.filtered_indices)
        total_count = len(self.media_items)
        summary = f"Showing {visible_count}/{total_count} {self.media_type_label}"
        if selected_count > 0:
            summary += f" | {selected_count} selected"
        content.append(("class:summary", summary))
        content.append(("", "\n"))
        content.append(("", "─" * 80))
        content.append(("", "\n"))

        return FormattedText(content)

    def _get_formatted_content(self) -> FormattedText:
        """Get the formatted text for media list."""
        content = []

        # Media items
        if not self.filtered_indices:
            content.append(("class:no-matches", f"No matching {self.media_type_label}"))
        else:
            for idx, item_idx in enumerate(self.filtered_indices):
                item = self.media_items[item_idx]
                is_selected = item_idx in self.selected_indices
                is_cursor = idx == self.cursor_position

                # Selection indicator
                prefix = "✓ " if is_selected else "  "

                # Style based on state
                if is_selected and is_cursor:
                    style = "class:selected-cursor"
                elif is_selected:
                    style = "class:selected"
                elif is_cursor:
                    style = "class:cursor"
                else:
                    style = "class:normal"

                # Media item info
                line = f"{prefix}{item.display_title} - {item.display_subtitle}"
                content.append((style, line))
                content.append(("", "\n"))

        return FormattedText(content)

    def _filter_media(self) -> None:
        """Filter media items based on search text."""
        if not self.search_text.strip():
            self.filtered_indices = list(range(len(self.media_items)))
        else:
            search_terms = self.search_text.lower().split()
            self.filtered_indices = []

            for i, item_str in enumerate(self.media_strings):
                if all(term in item_str for term in search_terms):
                    self.filtered_indices.append(i)

        # Adjust cursor position if needed
        if self.cursor_position >= len(self.filtered_indices):
            self.cursor_position = max(0, len(self.filtered_indices) - 1)

    def toggle_selection(self) -> None:
        """Toggle selection for current cursor position."""
        if self.filtered_indices:
            item_idx = self.filtered_indices[self.cursor_position]
            if item_idx in self.selected_indices:
                self.selected_indices.remove(item_idx)
            else:
                self.selected_indices.add(item_idx)

    def select_all_visible(self) -> None:
        """Select all visible media items."""
        self.selected_indices.update(self.filtered_indices)

    def move_cursor(self, direction: int) -> None:
        """Move cursor up or down."""
        if not self.filtered_indices:
            return

        self.cursor_position = max(
            0, min(len(self.filtered_indices) - 1, self.cursor_position + direction)
        )

    def add_search_text(self, text: str) -> None:
        """Add text to search query."""
        self.search_text += text
        self._filter_media()

    def remove_search_char(self) -> None:
        """Remove last character from search query."""
        self.search_text = self.search_text[:-1]
        self._filter_media()

    def clear_search(self) -> None:
        """Clear search query."""
        self.search_text = ""
        self._filter_media()

    def get_selected_media(self) -> list[MediaType]:
        """Get list of selected media items."""
        return [self.media_items[i] for i in sorted(self.selected_indices)]


def create_fzf_interface(
    media_items: list[MediaType], media_type_label: str = "movies"
) -> list[MediaType]:
    """
    Create an fzf-style interface for selecting media items.

    Args:
        media_items: List of available media items (movies or episodes)
        media_type_label: Label for the media type ("movies" or "episodes")

    Returns:
        List of selected media items
    """
    if not media_items:
        return []

    selected_items = []

    # Create the controls
    control = MultiSelectControl(media_items, media_type_label)
    header_control = FormattedTextControl(control._get_header_content)

    # Create key bindings
    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        control.move_cursor(-1)
        event.app.invalidate()

    @kb.add("down")
    def _(event):
        control.move_cursor(1)
        event.app.invalidate()

    @kb.add("k")
    def _(event):
        control.move_cursor(-1)
        event.app.invalidate()

    @kb.add("j")
    def _(event):
        control.move_cursor(1)
        event.app.invalidate()

    @kb.add(" ")
    def _(event):
        control.toggle_selection()
        event.app.invalidate()

    @kb.add("c-a")
    def _(event):
        control.select_all_visible()
        event.app.invalidate()

    @kb.add("escape", "a")
    def _(event):
        control.select_all_visible()
        event.app.invalidate()

    @kb.add("enter")
    def _(event):
        nonlocal selected_items
        # If nothing is selected, select the current cursor item (fzf behavior)
        if not control.selected_indices and control.filtered_indices:
            item_idx = control.filtered_indices[control.cursor_position]
            control.selected_indices.add(item_idx)
        selected_items = control.get_selected_media()
        event.app.exit()

    @kb.add("c-c")
    def _(event):
        event.app.exit()

    @kb.add("q")
    def _(event):
        event.app.exit()

    @kb.add("backspace")
    def _(event):
        control.remove_search_char()
        event.app.invalidate()

    @kb.add("escape")
    def _(event):
        event.app.exit()

    # Handle text input for search
    @kb.add("<any>")
    def _(event):
        # Only process single key presses
        if len(event.key_sequence) != 1:
            return

        key_press = event.key_sequence[0]

        # If the key is a Keys enum member, it's a special key (Control, Shift, Meta, etc.)
        # We only want printable characters for search, so skip all Keys enum members
        if isinstance(key_press.key, Keys):
            return

        # The key is a plain string - a regular printable character
        # Add it to the search text
        char = key_press.data if key_press.data else key_press.key
        if char and len(char) == 1 and char.isprintable():
            control.add_search_text(char)
            event.app.invalidate()

    # Create the layout with separate header and content windows
    root_container = HSplit(
        [
            # Fixed header with search and instructions
            Window(content=header_control, height=5, dont_extend_height=True),
            # Scrollable content window
            Window(content=control, wrap_lines=False),
        ]
    )

    # Create the application
    application: Application = Application(
        layout=Layout(root_container),
        key_bindings=kb,
        full_screen=True,
        mouse_support=False,
        style=Style.from_dict(
            {
                "search": "bold cyan",
                "normal": "",
                "cursor": "reverse",
                "selected": "green",
                "selected-cursor": "bold reverse green",
                "no-matches": "red",
                "instruction": "dim cyan",
                "summary": "bold yellow",
            }
        ),
    )

    # Run the application
    application.run()

    return selected_items


def select_movies_fzf(
    movies: list[Movie], target_lang: str = "fi", force_fzf: bool = False
) -> list[Movie]:
    """
    Select movies using an fzf-style interface.

    Args:
        movies: List of available movies
        target_lang: Target language code for display
        force_fzf: Force fzf interface even if terminal detection fails

    Returns:
        List of selected movies
    """
    if not movies:
        console.print(
            f"[yellow]No movies missing {target_lang} subtitles found.[/yellow]"
        )
        return []

    # Check if we're in an interactive terminal
    if not is_interactive_terminal() and not force_fzf:
        console.print(
            "[yellow]Warning: Not running in an interactive terminal[/yellow]"
        )
        console.print(
            f"[dim]stdin isatty: {sys.stdin.isatty()}, stdout isatty: {sys.stdout.isatty()}[/dim]"
        )
        console.print("[yellow]Falling back to standard selection...[/yellow]")
        console.print(
            "[dim]Tip: Use --force-fzf flag to try fzf interface anyway[/dim]"
        )
        from .cli_ui import select_movies_legacy

        return select_movies_legacy(movies, target_lang)

    # Show rich table first with movie count
    table = Table(
        title=f"Movies Missing {target_lang.upper()} Subtitles ({len(movies)} total)"
    )
    table.add_column("Count", style="cyan", width=6)
    table.add_column("Title", style="green")
    table.add_column("Year", style="yellow")
    table.add_column("Missing", style="red")

    for i, movie in enumerate(movies[:10], 1):  # Show first 10 as preview
        table.add_row(
            str(i) if i <= 10 else "...",
            movie.title,
            str(movie.year),
            ", ".join(movie.missing_subtitles),
        )

    if len(movies) > 10:
        table.add_row("", "...", f"and {len(movies) - 10} more", "")

    console.print(table)
    console.print()
    console.print("[blue]Starting fzf-style selection interface...[/blue]")
    console.print("[dim]Press Ctrl+C or q to exit the interface[/dim]")
    console.print()

    # Use the fzf interface
    try:
        selected = create_fzf_interface(cast(list[MediaType], movies), "movies")

        if selected:
            console.print(
                f"[green]Selected {len(selected)} movies for translation:[/green]"
            )
            for movie in cast(list[Movie], selected):
                console.print(f"  • {movie.title} ({movie.year})")
        else:
            console.print("[yellow]No movies selected.[/yellow]")

        return cast(list[Movie], selected)
    except KeyboardInterrupt:
        console.print("\n[yellow]Selection cancelled.[/yellow]")
        return []
    except OSError as e:
        console.print(f"[red]Terminal error: {e}[/red]")
        console.print(
            "[yellow]This may happen if running in a non-standard terminal[/yellow]"
        )
        console.print("[yellow]Falling back to standard selection...[/yellow]")
        from .cli_ui import select_movies_legacy

        return select_movies_legacy(movies, target_lang)
    except Exception as e:
        console.print(f"[red]Unexpected error in selection interface: {e}[/red]")
        # Fall back to the original interface
        console.print("[yellow]Falling back to standard selection...[/yellow]")
        # Import here to avoid circular dependency
        from .cli_ui import select_movies_legacy

        return select_movies_legacy(movies, target_lang)


def select_episodes_fzf(
    episodes: list[Episode], target_lang: str = "fi", force_fzf: bool = False
) -> list[Episode]:
    """
    Select episodes using an fzf-style interface.

    Args:
        episodes: List of available episodes
        target_lang: Target language code for display
        force_fzf: Force fzf interface even if terminal detection fails

    Returns:
        List of selected episodes
    """
    if not episodes:
        console.print(
            f"[yellow]No episodes missing {target_lang} subtitles found.[/yellow]"
        )
        return []

    # Check if we're in an interactive terminal
    if not is_interactive_terminal() and not force_fzf:
        console.print(
            "[yellow]Warning: Not running in an interactive terminal[/yellow]"
        )
        console.print(
            f"[dim]stdin isatty: {sys.stdin.isatty()}, stdout isatty: {sys.stdout.isatty()}[/dim]"
        )
        console.print("[yellow]Falling back to standard selection...[/yellow]")
        console.print(
            "[dim]Tip: Use --force-fzf flag to try fzf interface anyway[/dim]"
        )
        from .cli_ui import select_episodes_legacy

        return select_episodes_legacy(episodes, target_lang)

    # Show rich table first with episode count
    table = Table(
        title=f"Episodes Missing {target_lang.upper()} Subtitles ({len(episodes)} total)"
    )
    table.add_column("Count", style="cyan", width=6)
    table.add_column("Series", style="green")
    table.add_column("Episode", style="yellow")
    table.add_column("Title", style="blue")
    table.add_column("Missing", style="red")

    for i, episode in enumerate(episodes[:10], 1):  # Show first 10 as preview
        table.add_row(
            str(i) if i <= 10 else "...",
            episode.series_name,
            f"S{episode.season_number:02d}E{episode.episode_number:02d}",
            episode.episode_title,
            ", ".join(episode.missing_subtitles),
        )

    if len(episodes) > 10:
        table.add_row("", "...", "", f"and {len(episodes) - 10} more", "")

    console.print(table)
    console.print()
    console.print("[blue]Starting fzf-style selection interface...[/blue]")
    console.print("[dim]Press Ctrl+C or q to exit the interface[/dim]")
    console.print()

    # Use the fzf interface
    try:
        selected = create_fzf_interface(cast(list[MediaType], episodes), "episodes")

        if selected:
            console.print(
                f"[green]Selected {len(selected)} episodes for translation:[/green]"
            )
            for episode in cast(list[Episode], selected):
                console.print(f"  • {episode.display_title} - {episode.episode_title}")
        else:
            console.print("[yellow]No episodes selected.[/yellow]")

        return cast(list[Episode], selected)
    except KeyboardInterrupt:
        console.print("\n[yellow]Selection cancelled.[/yellow]")
        return []
    except OSError as e:
        console.print(f"[red]Terminal error: {e}[/red]")
        console.print(
            "[yellow]This may happen if running in a non-standard terminal[/yellow]"
        )
        console.print("[yellow]Falling back to standard selection...[/yellow]")
        from .cli_ui import select_episodes_legacy

        return select_episodes_legacy(episodes, target_lang)
    except Exception as e:
        console.print(f"[red]Unexpected error in selection interface: {e}[/red]")
        # Fall back to the original interface
        console.print("[yellow]Falling back to standard selection...[/yellow]")
        # Import here to avoid circular dependency
        from .cli_ui import select_episodes_legacy

        return select_episodes_legacy(episodes, target_lang)
