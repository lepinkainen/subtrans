"""Workflow functions for subtitle extraction and translation phases."""

import os
import subprocess
import sys
from pathlib import Path

import pysrt
from openai import OpenAI
from rich.columns import Columns
from rich.json import JSON
from rich.panel import Panel

from .core.cache import (
    clear_cached_subtitle,
    get_context_cache_path,
    load_cached_context,
    save_context_cache,
)
from .core.models import Config, MediaItem, TranslationContext
from .core.utils import console
from .integrations.bazarr import apply_path_mapping
from .processing.output import check_translation_exists, save_translated_subtitle
from .processing.subtitles import find_mkv_file, get_source_subtitle
from .processing.translator import analyze_subtitles, translate_subtitles_batch


# ----- Helpers -------------------------------------------------------------


def _print_phase_header(media: MediaItem, label: str, current: int, total: int) -> None:
    """Render the divider, progress indicator, and headline for a phase step."""
    console.print(f"\n[bold blue]{'=' * 60}[/bold blue]")
    progress = f" ({current}/{total})" if total > 1 else ""
    console.print(f"[bold blue]{label}: {media.display_title}{progress}[/bold blue]")
    if media.display_subtitle:
        console.print(f"[dim]{media.display_subtitle}[/dim]")


def _apply_and_announce_path_mapping(
    media: MediaItem, mappings: list[tuple[str, str]] | None
) -> None:
    """Apply NAS→local path mappings in-place and echo the resolved path."""
    original_path = media.path
    if mappings:
        media.path = apply_path_mapping(media.path, mappings)
    console.print(f"Path: {media.path}")
    if media.path != original_path:
        console.print(f"[dim](Original: {original_path})[/dim]")


def _print_validation_errors(errors: list) -> None:
    """Pretty-print up to ten pysrt validation errors with a tail summary."""
    console.print(f"[red]Found {len(errors)} subtitle validation errors:[/red]")
    for err in errors[:10]:
        console.print(
            f"  [yellow]#{err.position:3d}[/yellow] "
            f"[{err.error_type:12s}] {err.message}"
        )
    if len(errors) > 10:
        console.print(f"  [dim]... and {len(errors) - 10} more errors[/dim]")
    console.print(
        "[yellow]Subtitle has validation issues. This may indicate corruption.[/yellow]"
    )


def load_and_validate_subtitle(
    srt_path: Path,
    min_subtitle_count: int,
    strict_validation: bool,
) -> tuple[pysrt.SubRipFile | None, int]:
    """Load an SRT file (with encoding fallback) and validate the entry count.

    Returns (loaded_subtitles, entry_count). On failure / user-skip the first
    element is None. ``strict_validation`` enables an interactive c/r/s prompt
    when the entry count is below ``min_subtitle_count``.
    """
    try:
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

    if entry_count == 0:
        console.print(
            "[red]Error: No subtitle entries found - file may be in unsupported format[/red]"
        )
        console.print("[yellow]Supported format: SRT (.srt files)[/yellow]")
        return None, 0

    if entry_count < min_subtitle_count:
        console.print(
            f"[yellow]Warning: Only {entry_count} subtitle entries found "
            f"(expected at least {min_subtitle_count} for typical movies)[/yellow]"
        )
        console.print(
            "[yellow]This could indicate a corrupted cache, incomplete extraction, "
            "or a very short video (trailer, short film, etc.)[/yellow]"
        )

        if strict_validation:
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
                if choice == "r":
                    if clear_cached_subtitle(srt_path):
                        console.print(
                            f"[blue]Deleted cached subtitle: {srt_path}[/blue]"
                        )
                        console.print("[blue]Will re-extract from MKV[/blue]")
                    else:
                        console.print(
                            "[yellow]Subtitle is not in cache; cannot re-extract.[/yellow]"
                        )
                    return None, 0
                if choice == "c":
                    console.print("[blue]Continuing with low-entry subtitle...[/blue]")
                    break
                console.print("[red]Invalid choice. Use c, r, or s.[/red]")

    return subs, entry_count


# ----- Phase 1 / Phase 2 ---------------------------------------------------


def process_phase1(
    media: MediaItem,
    client: OpenAI | None,
    config: Config,
    *,
    current_index: int = 1,
    total: int = 1,
    extract_only: bool = False,
) -> bool:
    """Phase 1: extract subtitle, optionally analyze context, prompt for approval.

    Returns True if the user approved (or extract-only succeeded), False if
    cancelled or errored.
    """
    _print_phase_header(media, "Processing", current_index, total)
    _apply_and_announce_path_mapping(media, config.path_mappings or None)

    srt_path, skip_requested = get_source_subtitle(
        media,
        config,
        config.source_language,
        min_entries=config.min_subtitle_count,
        min_file_size=config.min_subtitle_file_size,
    )

    if skip_requested:
        console.print(f"[yellow]Skipped {media.display_title}[/yellow]")
        return False

    if not srt_path:
        console.print(f"[red]Could not find {config.source_language} subtitle[/red]")
        return False

    subs, _ = load_and_validate_subtitle(
        srt_path, config.min_subtitle_count, config.strict_validation
    )

    if subs is None:
        return False

    if config.validate_subtitles:
        errors = subs.validate(
            min_duration_ms=config.min_duration_ms,
            max_duration_secs=config.max_duration_secs,
            min_text_length=config.min_text_length,
            max_text_length=config.max_text_length,
        )
        if errors:
            _print_validation_errors(errors)
            return False

    if extract_only:
        console.print(
            "[yellow]Extract-only mode - subtitle cached successfully[/yellow]"
        )
        return True

    if config.dry_run:
        console.print("[yellow]Dry run - skipping analysis[/yellow]")
        return True

    if config.skip_analysis:
        return True

    if client is None:
        console.print("[red]OpenAI client not configured; cannot run analysis.[/red]")
        return False

    return _run_analysis_and_approve(media, subs, client, config, total=total)


def _run_analysis_and_approve(
    media: MediaItem,
    subs: pysrt.SubRipFile,
    client: OpenAI,
    config: Config,
    *,
    total: int,
) -> bool:
    """Pass-1 analysis + interactive approval.

    Returns True if context is approved (or auto-approved from cache in batch).
    """
    cached = load_cached_context(media)

    if cached is not None and total > 1:
        console.print("[blue]Using cached context from previous analysis[/blue]")
        console.print("[green]Auto-accepting cached context (batch mode)[/green]")
        return True

    if cached is not None:
        console.print("[blue]Using cached context from previous analysis[/blue]")
        context = cached
    else:
        context = analyze_subtitles(
            subs,
            client,
            media.analyze_title,
            model=config.analysis_model,
            source_lang=config.source_language,
            target_lang=config.target_language,
            movie_year=media.analyze_year,
            log_token_usage=config.log_token_usage,
            service_tier=config.analysis_service_tier,
        )
        if config.save_context and context.raw_json:
            save_context_cache(context, media)

    if not (context and context.raw_json):
        return True

    console.print("\n[bold blue]Translation Context (Pass 1 Analysis):[/bold blue]")
    panel = Panel(
        JSON.from_data(context.raw_json, indent=2),
        title=f"Context for {media.display_title}",
        title_align="left",
        border_style="blue",
    )
    console.print(panel)

    console.print("\n[yellow]Approve this context for translation? [Y/n/e/d][/yellow]")
    console.print("[dim]Y=yes, n=no, e=edit context JSON, d=diff with cached[/dim]")
    response = input("> ").strip().lower()

    if response == "e":
        response = _handle_context_edit(media, context)
    elif response == "d":
        response = _handle_context_diff(media, context)

    if response and response not in ("y", "yes", ""):
        console.print("[yellow]Context not approved - skipped.[/yellow]")
        return False

    if config.save_context and context.raw_json:
        save_context_cache(context, media)
        console.print("[green]Context saved to cache[/green]")
    return True


def process_phase2(
    media: MediaItem,
    client: OpenAI,
    config: Config,
    *,
    current_index: int = 1,
    total: int = 1,
) -> bool:
    """Phase 2: load cached context, translate, save output."""
    _print_phase_header(media, "Translating", current_index, total)
    _apply_and_announce_path_mapping(media, config.path_mappings or None)

    exists, existing_path = check_translation_exists(
        media, target_lang=config.target_language
    )
    if exists:
        console.print(f"[yellow]Translation already exists: {existing_path}[/yellow]")
        console.print("[yellow]Skipping re-translation[/yellow]")
        return True

    srt_path, skip_requested = get_source_subtitle(
        media,
        config,
        config.source_language,
        min_entries=config.min_subtitle_count,
        min_file_size=config.min_subtitle_file_size,
        skip_interactive=True,
    )

    if skip_requested:
        console.print(f"[yellow]Skipped {media.display_title}[/yellow]")
        return False

    if not srt_path:
        console.print(f"[red]Could not find {config.source_language} subtitle[/red]")
        return False

    subs, _ = load_and_validate_subtitle(
        srt_path, config.min_subtitle_count, config.strict_validation
    )
    if subs is None:
        return False

    if config.dry_run:
        console.print("[yellow]Dry run - skipping translation[/yellow]")
        return True

    context = load_cached_context(media)
    if context:
        console.print("[blue]Using cached context from Phase 1[/blue]")
    else:
        console.print(
            "[yellow]Warning: No cached context found, translating without context[/yellow]"
        )

    translated = translate_subtitles_batch(
        subs,
        client,
        media.analyze_title,
        context=context,
        batch_size=config.batch_size,
        model=config.translation_model,
        source_lang=config.source_language,
        target_lang=config.target_language,
        validate_translation=config.validate_translation,
        min_translation_difference=config.min_translation_difference,
        movie_year=media.analyze_year,
        log_token_usage=config.log_token_usage,
        service_tier=config.translation_service_tier,
    )

    if config.fix_overlaps:
        console.print("[blue]Fixing overlapping subtitles...[/blue]")
        translated.fix_overlaps(buffer_ms=config.overlap_buffer_ms)

    mkv_path = find_mkv_file(media.path)
    output_path = save_translated_subtitle(
        translated, media, mkv_path, target_lang=config.target_language
    )
    console.print(
        f"[bold green]Saved {config.target_language} subtitles: {output_path}[/bold green]"
    )
    return True


# ----- Edit / diff helpers (kept stable) ----------------------------------


def _handle_context_edit(media: MediaItem, context: TranslationContext) -> str:
    """Open the cached-context JSON in $EDITOR; reload and reprompt on save."""
    context_path = get_context_cache_path(media)
    if not context_path.exists():
        save_context_cache(context, media)

    editor = os.environ.get("EDITOR", "nano" if sys.platform != "win32" else "notepad")

    try:
        console.print(f"[blue]Opening {context_path} with {editor}...[/blue]")
        subprocess.run([editor, str(context_path)], check=True)

        edited = load_cached_context(media)
        if edited:
            console.print("[green]Context reloaded after editing[/green]")
            panel = Panel(
                JSON.from_data(edited.raw_json, indent=2),
                title=f"Edited Context for {media.display_title}",
                title_align="left",
                border_style="green",
            )
            console.print(panel)
            console.print(
                "\n[yellow]Approve edited context for translation? [Y/n][/yellow]"
            )
            return input("> ").strip().lower()
        console.print("[red]Failed to reload edited context, using original[/red]")
        return "n"
    except subprocess.CalledProcessError:
        console.print(f"[red]Failed to open editor '{editor}'[/red]")
        return "n"
    except FileNotFoundError:
        console.print(
            f"[red]Editor '{editor}' not found. "
            "Please set EDITOR environment variable.[/red]"
        )
        return "n"
    except Exception as e:
        console.print(f"[red]Error editing context: {e}[/red]")
        return "n"


def _handle_context_diff(media: MediaItem, context: TranslationContext) -> str:
    """Show side-by-side diff between current and cached context, then reprompt."""
    cached_context = load_cached_context(media)
    if cached_context and cached_context.raw_json != context.raw_json:
        console.print(
            "[blue]Showing differences between current and cached context:[/blue]"
        )
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

        console.print(
            "\n[yellow]Approve this context for translation? [Y/n/e][/yellow]"
        )
        console.print("[dim]Y=yes, n=no, e=edit current context[/dim]")
        response = input("> ").strip().lower()
        if response == "e":
            return _handle_context_edit(media, context)
        return response

    console.print(
        "[yellow]No differences found or no cached context available[/yellow]"
    )
    console.print("\n[yellow]Approve this context for translation? [Y/n/e][/yellow]")
    console.print("[dim]Y=yes, n=no, e=edit current context[/dim]")
    response = input("> ").strip().lower()
    if response == "e":
        return _handle_context_edit(media, context)
    return response
