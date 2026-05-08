# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`subtrans` is a Python 3.14 tool that translates subtitles between languages using OpenAI GPT models. It integrates with Bazarr to discover movies and TV episodes missing target-language subtitles, then runs a two-phase context-aware translation pipeline.

Single-user, private use. NAS-aware (SMB path mappings). Cache persistence is intentional.

## Commands

Use `task` (Taskfile.yml) as the canonical entry point. Do not invoke `pytest` / `ruff` / `mypy` directly when a task wraps them.

```bash
task build      # lint + test + build wheel/sdist (run before claiming done)
task test       # pytest -q (ignore llm-shared)
task test-ci    # pytest with coverage (xml + term)
task lint       # ruff check --fix, ruff format, mypy (autofix flow)
task clean      # nuke build/, .mypy_cache, .ruff_cache, .pytest_cache
```

Run a single test:

```bash
uv run pytest tests/core/test_cache.py::test_name -v
uv run pytest -k "pattern" -v
```

Run the app:

```bash
uv run subtrans                       # movies, interactive (fzf-style)
uv run subtrans --series              # TV episodes
uv run subtrans --extract-only        # cache subtitles, no translation, no API key required
uv run subtrans --select "*matrix*"   # non-interactive glob (case-insensitive)
uv run subtrans --legacy-selection    # numbered prompt instead of fzf
uv run subtrans --force-fzf           # force fzf when terminal detection fails
uv run subtrans --stats               # token usage / cost summary, then exit
uv run subtrans --stats --movie X     # filter stats by title
uv run subtrans -c custom.yml         # custom config path
```

Lint autofix workflow (per AGENTS.md): run `task lint` rather than hand-editing format errors line-by-line.

## Architecture

### Two-phase workflow with human approval gate

`cli.py:_main_impl` → orchestrates. The defining shape:

1. **Phase 1 — Context Analysis** runs over every selected item *first*. For each, `process_movie_phase1` / `process_episode_phase1` (in `workflows.py`) extracts subtitles, runs analysis, displays the JSON context, and prompts `Y/n/e/d` (approve / skip / edit-in-$EDITOR / diff-vs-cached). Approved items collect into a list.
2. **Phase 2 — Translation** then runs unattended over only the approved items. This split exists so the user can review and edit *all* character/place/term mappings up front, then walk away while the expensive batch translation runs.

Do not collapse the phases. The approval gate is the design.

### Hybrid service-tier cost model

Both passes use `gpt-5` (configurable). The tiers differ:

- Pass 1 → `service_tier="auto"` (standard pricing). Fast responses for interactive review.
- Pass 2 → `service_tier="flex"` (50% discount, slower, automatic prompt caching gives 90% off cached tokens). Longer client timeout (~900s) accommodates Flex queueing. 429 "Resource Unavailable" is retried.

Preserve this separation when modifying the OpenAI client layer.

### Subtitle source priority

`processing/subtitles.py:get_source_subtitle`:

1. External SRT next to the video (`*.<lang>.srt`, then any `*.srt` fallback).
2. Embedded MKV tracks via `mkvmerge -J`, filtered to text codecs (PGS/VobSub image-based tracks are dropped). Extracted with `mkvextract tracks` to `~/.cache/subtrans/<md5>.srt`.

Track selection respects `interactive_track_selection` / `auto_select_tracks`. SDH and forced flags surface in the picker.

### Media abstraction

`core/models.py` defines a `MediaItem` Protocol implemented by `Movie` and `Episode`. Workflow functions branch on `--series` but share underlying logic via `display_title`, `cache_key`, `file_path`, and `path`. `core/media_types.py` provides `is_movie` / `is_episode` guards used by `cache.py` for context-cache filename derivation:

- Movie: `{title}_{year}_context.json`
- Episode: `{series}_S##E##_{series_year}_context.json`

Episodes also expose `series_cache_key` for series-wide context sharing.

### Post-translation validation

After Pass 2, output goes through pysrt validation (duration bounds, text length bounds, entry count) and overlap fixing (`overlap_buffer_ms` minimum gap). Controlled by `validate_subtitles` and `fix_overlaps` config keys. **Note**: `pysrt` is pinned to a custom fork in `pyproject.toml`: `git+https://github.com/lepinkainen/pysrt.git@main`.

### Token logging & pricing

`core/token_logger.py` records every API call to a JSONL log. `pricing.yml` maps model + tier → USD/1M tokens. `--stats` aggregates the log into a cost report, optionally filtered by title. When adding a new model, update `pricing.yml`.

### Prompts

Analysis prompts live as **external files** in `subtrans/prompts/analysis_prompt.txt` and `analysis_prompt.fi.txt` (target-language-specific). Edit these to tune Pass 1 extraction — do not hardcode in `translator.py`.

### Selection UI

`selection.py` + `cli_ui.py` implement two pickers: an fzf-style live filter (default) and a legacy numbered list (`--legacy-selection`). `--select PATTERN` bypasses both with a glob match. Episode selection supports series/season grouping.

### Bazarr integration

`integrations/bazarr.py`:

- `get_wanted_movies` / `get_wanted_episodes`: fetch missing-target items, filter to those that *also* have a source-language subtitle available (otherwise translation is impossible). Skipped items are logged.
- `_has_source_subtitle`: case-insensitive prefix match across `code2`/`code3`/`language` fields, null-safe.
- `populate_movie_path` / `populate_episode_path`: lazy fetch full paths/years post-selection (the `wanted` API omits these).
- `apply_path_mapping`: prefix-replace NAS → local mount; first match wins. Applied at the start of each phase, before any FS access.

The `wanted` endpoint does not return `year`, so the selection UI shows `(0)` until paths are populated. For >100 movies a dim note explains this.

## Config (`config.yml`)

Loaded via `core/config.py:load_config`. Full schema: `Config` dataclass in `core/models.py`. Keep `config.example.yml`, the dataclass, and any tests in sync when adding fields.

Notable behavior flags:

- `dry_run`: list selections, no API calls, no writes.
- `skip_analysis`: bypass Pass 1 (faster, less consistent translations).
- `save_context`: persist Pass 1 JSON for review/reuse.
- `validate_translation` + `min_translation_difference`: detect untranslated passthroughs.
- `strict_validation`: hard-prompt on low entry counts; offers continue / re-extract / skip.
- `interactive_track_selection` vs `auto_select_tracks`: MKV picker behavior.

OpenAI API key resolves from `openai.api_key` in YAML or `OPENAI_API_KEY` env var.

## Cache layout (`~/.cache/subtrans/`)

- `<md5(mkv_path:track_id)>.srt` — extracted MKV subtitle tracks
- `<title>_<year>_context.json` (movies) / `<series>_S##E##_<year>_context.json` (episodes) — Pass 1 context, when `save_context: true`
- Token-usage JSONL — append-only, read by `--stats`

Cache is persistent. Don't clear without user consent. During development, stale cache can mask bugs — `task clean` does *not* touch `~/.cache/subtrans/`.

## External tools

- `mkvtoolnix` (system-wide): provides `mkvmerge` and `mkvextract`. `brew install mkvtoolnix` / `apt install mkvtoolnix`. Missing binary surfaces a graceful error with install instructions.

## Issue tracker

`bd` (beads) is used locally; DB lives in `.beads/`. `bd ready` lists unblocked issues. `bd dep add <issue> <blocker>` records dependencies. Auto-syncs with git via JSONL.

## Modification patterns

- **New config option**: add to `Config` → `load_config` → `config.example.yml` → tests, then thread through `cli.py` → `workflows.py` call sites.
- **New CLI flag**: `cli_args.py` only (single argparse definition).
- **New media type**: implement `MediaItem` Protocol, add `is_<type>` guard in `media_types.py`, extend `cache.py:get_context_cache_path`, add Bazarr fetch/populate helpers, branch in `cli.py:_main_impl`.
- **New OpenAI model**: add entry to `pricing.yml` so `--stats` can compute cost.
- **Modifying analysis output**: edit `subtrans/prompts/analysis_prompt*.txt`, then update `TranslationContext` dataclass + `cache.py:load_cached_context` mapping if you add fields.

## Constraints

- All output files UTF-8 (subtitle standard). Loader falls back to latin-1 only on read.
- Path mapping must be applied before any FS access in a phase function.
- Don't bypass the Phase 1 approval gate.
- Don't collapse the analysis/translation tier split (cost-load-bearing).
- Tests must not hit live OpenAI or Bazarr — mock both. If a feature can't reasonably be unit-tested, leave it untested with a comment, per AGENTS.md.
- No "test scripts" or "demo scripts" — write actual unit tests instead.
