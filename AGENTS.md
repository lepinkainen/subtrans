# Repository Guidelines

## Project Structure & Module Organization

- `subtrans/cli.py` is the entrypoint (`uv run subtrans` or `uv run main.py`); it wires config, Bazarr fetch, analysis, translation, and output saving.
- `subtrans/core` holds configuration parsing, dataclasses, caching, and console utilities (cache lives under `~/.cache/subtrans`).
- `subtrans/processing` manages subtitle discovery/extraction, translation passes, and output writing.
- `subtrans/integrations` contains Bazarr API helpers and path-mapping logic.
- Tests mirror the package layout in `tests/` (unit + light integration), and configuration samples live in `config.example.yml` / `config.yml`.

## Build, Test, and Development Commands

- Build: `task build` - Always run this before claiming a task is done it will lint and test all changes. Don't assume test failures are "pre-existing" all test failures are your responsibility to fix.
- Test: `task test` - Use this command to run tests
- Install deps: `uv sync`.
- Run the translator (default config): `uv run subtrans` or `uv run main.py --config config.yml`.
- Quick dry run without translation: `uv run subtrans -- --dry-run`.
- Extract-only mode (cache English subs): `uv run subtrans -- --extract-only`.
- Fix formatting errors: `uv run ruff check --fix` followed by `uv run ruff format` instead of editing files line by line. Running `task lint` will run both automatically.

## Coding Style & Naming Conventions

- Python 3.14, 4-space indentation, PEP 8-aligned; keep type hints on public functions and dataclasses for shared models.
- Use snake_case for functions/variables, PascalCase for classes, and descriptive argparse flag names (mirroring existing CLI).
- Favor small, pure helpers in `processing/` and `core/`; keep Rich console messaging concise and user-facing.
- When touching config or models, keep defaults in sync with `config.example.yml` and CLI defaults.

## Testing Guidelines

- Add/extend tests under `tests/` using `pytest`; name files `test_*.py` and functions `test_*`.
- Prefer deterministic tests: mock OpenAI and Bazarr HTTP calls; avoid live network I/O.
- Cover new CLI flags and error paths (e.g., missing subtitles, path mapping misses). Use sample paths like `/volume1/movies` → `/Volumes/NAS/movies` for regression cases.

## Commit & Pull Request Guidelines

- Follow the existing conventional style: `feat: ...`, `fix: ...`, `chore: ...` (short, imperative).
- PRs should note scope, flags/config touched, and any user-facing messaging changes. Link issues when relevant.
- Include how you verified changes (`uv run pytest`, sample run command) and mention if secrets/config files were excluded from the diff.

## Security & Configuration Tips

- Do not commit `config.yml` or real API keys; use `config.example.yml` as the template and set `OPENAI_API_KEY` via environment.
- If testing against Bazarr, use non-production endpoints or mocks and scrub logs. Clear caches in `~/.cache/subtrans` if stale context/subtitles cause confusion.

## bd Issue Tracker

- Initialize the local bd database in the repo before use: `bd init` (or `bd init --prefix <prefix>`), which creates the SQLite DB.
- Create and manage issues with dependency awareness: `bd create "Title" [-p priority] [-t type]`, add blockers with `bd dep add <issue> <blocker>`, and inspect trees with `bd dep tree <issue>`.
- Use `bd ready` to list open issues with no blocking dependencies; run it from the repo root so bd can auto-discover the local database or fall back to your default.
- bd auto-syncs with git via JSONL import/export (debounced); keep the generated artifacts under version control if you want team sharing, or set `--no-auto-*` flags to disable.
