# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Subtitle Translator (`subtrans`) - A Python tool that translates English subtitles to Finnish using OpenAI GPT models with a **two-model architecture** for cost optimization. The tool integrates with Bazarr to automatically find movies missing Finnish subtitles and performs context-aware translation using a two-pass approach.

### Two-Model Architecture with Flex Pricing

The translation system uses `gpt-5` for both phases with different service tiers for cost optimization:

- **Pass 1 (Context Analysis)**: `gpt-5` with `service_tier="auto"` (Standard pricing)
  - Handles complex rule interpretation and entity extraction
  - Processes comprehensive JSON style guides
  - Extracts character names, places, terms, genre, tone, and formality
  - Multilingual context understanding (English/Spanish/Finnish code-switching)
  - Uses standard tier for fast, interactive responses during human review

- **Pass 2 (Translation)**: `gpt-5` with `service_tier="flex"` (50% discount)
  - Cost-effective translation guided by Pass 1 context
  - Executes straightforward translation following established rules
  - Uses Flex tier for 50% cost savings (can be slower, runs unattended)
  - Automatic prompt caching with Flex tier (90% discount on cached tokens)
  - Benefits from detailed character/place/term mappings from analysis

This hybrid approach provides the best balance of responsiveness and cost:
- Pass 1 uses standard tier for fast responses during interactive context review
- Pass 2 uses Flex tier for significant cost savings on batch translation work

## Development Commands

### Setup
1. Copy `config.example.yml` to `config.yml`
2. Edit `config.yml` with your Bazarr URL and API key
3. Set environment variable: `export OPENAI_API_KEY=your_key_here`
4. Configure path mappings if running from laptop with NAS mounted via SMB
5. Configure analysis and translation models (default: `gpt-5` with hybrid service tiers)

### Running the application
```bash
# Run with default config file (config.yml)
uv run subtrans

# Use a different config file
uv run subtrans --config /path/to/other-config.yml
uv run subtrans -c custom-config.yml

# Extract and cache subtitles only (no translation)
# Useful for batch pre-population of the cache
uv run subtrans --extract-only
uv run subtrans -e
```

**Two-Phase Workflow with Context Review**: The tool uses a two-phase workflow where Phase 1 (Context Analysis) processes ALL selected movies first, displaying the extracted context from Pass 1 in a pretty-printed JSON format and waiting for your approval for each movie. Phase 2 (Translation) then translates only the approved movies using their cached contexts. This allows you to review and potentially edit all character names, places, and terminology upfront before the expensive translation pass runs unattended.

### Configuration File (config.yml)
All settings are managed via YAML config file:

```yaml
# Bazarr API settings
bazarr:
  url: "http://localhost:6767"
  api_key: "YOUR_BAZARR_API_KEY_HERE"

# OpenAI settings (API key from OPENAI_API_KEY environment variable)
# Hybrid service tier approach for cost optimization:
# - Pass 1 uses "auto" (standard) tier for fast interactive responses
# - Pass 2 uses "flex" tier for 50% cost savings (can be slower)
openai:
  analysis_model: "gpt-5"       # Pass 1: Context analysis
  translation_model: "gpt-5"    # Pass 2: Translation
  batch_size: 50                # Number of subtitles per API call
  analysis_service_tier: "auto" # Standard tier for Pass 1 (fast, interactive)
  translation_service_tier: "flex" # Flex tier for Pass 2 (50% discount)

# Path mappings - Map NAS paths to local mount points
path_mappings:
  - from: "/volume1/movies"
    to: "/Volumes/NAS/movies"

# Translation options
translation:
  skip_analysis: false      # Skip context analysis for faster translation
  save_context: true        # Save translation context as JSON
  dry_run: false           # List movies without translating
```

See `config.example.yml` for full configuration options and detailed comments.

### Python environment
- Use `uv` for all Python operations (dependency management, running scripts)
- Python version: 3.14+
- Entry point: `uv run subtrans` (configured in pyproject.toml)

### External dependencies
- **mkvtoolnix**: Required for extracting subtitle tracks from MKV files
  - Commands used: `mkvmerge`, `mkvextract`
  - Must be installed system-wide
  - Installation: `brew install mkvtoolnix` (macOS) or via package manager

### Cache
- **Subtitle cache**: `~/.cache/subtrans/`
  - Extracted subtitles cached by MD5 hash of `{mkv_path}:{track_id}`
  - Persistent across runs for faster development
- **Context cache**: `~/.cache/subtrans/`
  - Translation context saved as `{movie_title}_{year}_context.json`
  - Enabled with `save_context: true` in config
  - Can be reviewed or reused for consistency

## Architecture

### Project Structure

```
subtrans/
├── subtrans/              # Main package
│   ├── core/              # Core functionality
│   │   ├── models.py      # Data models (Movie, SubtitleTrack, Config, TranslationContext)
│   │   ├── config.py      # Configuration loading from YAML
│   │   ├── cache.py       # Cache management for subtitles & contexts
│   │   └── utils.py       # Shared utilities (console, CACHE_DIR)
│   ├── integrations/      # External service integrations
│   │   └── bazarr.py      # Bazarr API client and path mapping
│   ├── processing/        # Subtitle processing
│   │   ├── subtitles.py   # Subtitle discovery & extraction (MKV + external SRT)
│   │   ├── translator.py  # Two-pass translation logic
│   │   └── output.py      # File output operations
│   └── cli.py             # CLI entry point and orchestration
├── tests/                 # Comprehensive test suite
│   ├── core/              # Core module tests
│   ├── integrations/      # Integration tests
│   └── processing/        # Processing module tests
├── config.example.yml     # Example configuration
└── pyproject.toml         # Python project metadata
```

### Two-Pass Translation Approach

**Pass 1: Context Analysis** (`analyze_subtitles`)
- **Model**: `gpt-4o` (configurable via `config.yml`)
- **Purpose**: Extract comprehensive context from complete subtitle file
- **Process**:
  - Combines all subtitle text into a single analysis request
  - Sends to GPT with structured JSON response format
  - Extracts critical context:
    - **Characters**: Name mappings and Finnish handling (keep/translate)
    - **Places**: Location names and their Finnish equivalents
    - **Terms**: Recurring phrases, catchphrases, technical terminology
    - **Genre**: Movie genre (action, comedy, drama, etc.)
    - **Tone**: Emotional tone (serious, light-hearted, mixed)
    - **Formality**: Finnish formality level (formal "te" vs informal "sinä")
    - **Style notes**: Slang, accents, time period, special handling
- **Caching**: Results stored in `TranslationContext` dataclass
- **Optional persistence**: Saved as JSON file with `save_context: true`
- **Skip option**: Can be disabled with `skip_analysis: true` for faster (but less consistent) results

**Pass 2: Batch Translation** (`translate_subtitles_batch`)
- **Model**: `gpt-4o-mini` (configurable via `config.yml`)
- **Purpose**: Translate subtitles using context from Pass 1
- **Process**:
  - Translates in configurable batches (default: 50 subtitles per API call)
  - Uses extracted context to build comprehensive system prompt:
    - Character name handling rules
    - Place name translations
    - Recurring term mappings
    - Genre and tone guidance
    - Formality level (te/sinä selection)
  - Maintains consistency by referencing Pass 1 context throughout
  - Processes with progress indicator using `rich` library
  - Separator: `\n---\n` between subtitle entries
  - Position markers: "(Beginning of movie)" and "(End of movie)"
- **Error handling**: Gracefully handles batch parsing errors (falls back to original text)

**System Prompt Construction** (`build_translation_prompt`)
- Incorporates all extracted context from Pass 1
- Provides translation guidelines:
  - Natural, idiomatic Finnish
  - Screen-fit line lengths (subtitle constraints)
  - Idiom and cultural reference handling
  - Character voice consistency

### Subtitle Source Priority

The tool searches for English subtitles in this order:

1. **External SRT files** (`find_external_srt`):
   - Pattern matching: `*.en.srt`, `*.EN.srt`, `*.[Ee]ng*.srt`, `*.[Ee]nglish*.srt`
   - Falls back to any `*.srt` file if no English-specific file found
   - Faster and preferred over MKV extraction

2. **Embedded MKV subtitles** (`get_mkv_subtitle_tracks`):
   - Extracts track info using `mkvmerge -J`
   - Filters out image-based subtitles (PGS, VobSub)
   - Searches for English track (language code: eng/en/english)
   - Falls back to first text subtitle track if no English track found
   - Extracts to cache using `mkvextract tracks`

### Data Models

**Movie** (`subtrans/core/models.py:7-16`)
- `radarr_id: int`: Radarr identifier
- `title: str`, `year: int`: Movie metadata
- `path: str`: File system path to movie
- `missing_subtitles: list[str]`: List of missing language codes
- `existing_subtitles: list[dict]`: Currently available subtitles

**SubtitleTrack** (`subtrans/core/models.py:19-26`)
- `track_id: int`: MKV track identifier
- `language: str`: ISO language code
- `name: str`: Track name/description
- `codec: str`: Subtitle codec (filters out image-based formats)

**Config** (`subtrans/core/models.py:29-40`)
- `bazarr_url: str`, `bazarr_api_key: str`: Bazarr server details
- `analysis_model: str`: OpenAI model for Pass 1 (context analysis)
- `translation_model: str`: OpenAI model for Pass 2 (translation)
- `batch_size: int`: Subtitles per API call
- `path_mappings: list[tuple[str, str]]`: NAS to local path mappings
- `skip_analysis: bool`, `save_context: bool`, `dry_run: bool`: Behavior flags

**TranslationContext** (`subtrans/core/models.py:43-54`)
- `characters: dict[str, str]`: Character name translation mapping
- `places: dict[str, str]`: Place name translation mapping
- `terms: dict[str, str]`: Recurring term translation mapping
- `genre: str`, `tone: str`, `formality: str`: Style metadata
- `style_notes: str`: Additional translation guidance
- `raw_json: dict`: Complete JSON response for persistence

### Output Format

Translated subtitles are saved with Finnish language suffix:
- **Pattern**: `<movie_name>.fi.srt`
- **Encoding**: UTF-8
- **Location**: Same directory as source video file
- **Fallback**: If NAS write fails, saves to local cache directory
- **Cleanup**: Temporary extracted subtitles are kept in cache for reuse

### Bazarr Integration

**Movie Discovery** (`integrations/bazarr.py`):
- Uses Bazarr REST API to query movies with missing subtitles
- Filters for movies missing target language (e.g., Finnish)
- **Filters to only include movies with source language subtitles available (e.g., English)**
- **Skips movies without source subtitles with console logging**
- Interactive movie selection with rich table display

**API endpoints**:
- `/api/movies/wanted` - Get movies with missing subtitles
- `/api/movies` - Get detailed movie information (including file path)

**Functions**:
- `_has_source_subtitle()`: Helper function to check for source language subtitle availability
  - Checks multiple language code fields (code2, code3, language)
  - Null-safe handling of missing language codes
  - Case-insensitive matching with prefix support (handles "en", "eng", "english")
  - Returns tuple of (has_source, found_language_codes) for filtering and logging
- `get_wanted_movies()`: Fetch and filter movies missing target language subtitles
  - Only returns movies with both missing target language AND available source language
  - Logs skipped movies with detected languages
- `populate_movie_path()`: Fetch full file path for selected movies

### Path Mapping

When running on a laptop with NAS mounted via SMB, Bazarr returns NAS-relative paths that need to be mapped to local mount points.

**Function**: `apply_path_mapping(path, path_mappings)`
- Takes a list of `(from_path, to_path)` tuples from config
- Replaces the `from_path` prefix with `to_path` for each movie path
- Supports multiple mappings for different mount points
- First matching prefix wins
- Applied before any file operations (finding MKV, extracting subtitles, saving output)

**Usage pattern in config.yml**:
```yaml
path_mappings:
  - from: "/volume1/movies"
    to: "/Volumes/NAS/movies"
  - from: "/volume2/films"
    to: "/Volumes/NAS2/films"
```

**Implementation**: Applied at the start of `process_movie()` by modifying `Movie.path` before any file operations.

### Cache System

**Subtitle Extraction Cache** (`core/cache.py`):
- **Location**: `~/.cache/subtrans/`
- **Filename**: MD5 hash of `{mkv_path}:{track_id}.srt`
- **Purpose**: Avoid repeated MKV extraction (slow operation)
- **Persistence**: Kept across runs for development speed
- **Function**: `get_subtitle_cache_path(mkv_path, track_id)`

**Translation Context Cache** (`core/cache.py`):
- **Location**: `~/.cache/subtrans/`
- **Filename**: `{sanitized_movie_title}_{year}_context.json`
- **Sanitization**: Special characters and spaces converted to underscores
- **Purpose**: Review/reuse context analysis, avoid repeated expensive analysis
- **Enabled**: Via `save_context: true` in config
- **Functions**:
  - `save_context_cache(context, movie_title, year)`
  - `load_cached_context(movie_title, year)`

### CLI Orchestration

**Main workflow** (`cli.py:main()`):
1. Parse command-line arguments (`--config`, `-c`, `--extract-only`, `-e`)
2. Load configuration from YAML
3. Display configuration info (Bazarr URL, models, batch size, path mappings)
4. Check `OPENAI_API_KEY` environment variable (skipped if `--extract-only`)
5. Fetch wanted movies from Bazarr
6. Interactive movie selection with rich table
7. Fetch full paths for selected movies
8. **If extract-only mode**: Extract and cache subtitles for all selected movies, then exit
9. **Phase 1 (Context Analysis)**: Process all selected movies with `process_movie_phase1()`
   - For each movie: extract subtitle, analyze context, display JSON, wait for user approval
   - Track approved movies (user can skip movies by declining approval)
   - Exit if no movies approved
10. **Phase 2 (Translation)**: Process approved movies with `process_movie_phase2()`
   - For each approved movie: load cached context, translate, save output
11. Report summary (success count)

**Phase 1 processing** (`cli.py:process_movie_phase1()`):
1. Apply path mappings (NAS → local)
2. Find source language subtitle (external SRT or MKV extraction with caching)
3. Load subtitle with UTF-8 (fallback to latin-1 encoding)
4. **If `extract_only=True`**: Return success (subtitle is now cached)
5. Skip processing if `dry_run` mode enabled
6. **Context Analysis** (unless `skip_analysis=True`):
   - Check context cache first (by movie title/year)
   - Run analysis with `gpt-4o` if not cached
   - Save context if `save_context=True`
   - **Always display context** in pretty-printed JSON format
   - Wait for user approval (Y/n/e/d options):
     - Y: Approve and continue to Phase 2
     - n: Skip this movie
     - e: Edit context JSON with $EDITOR, reload, display, ask again
     - d: Show diff with cached context, then ask again
7. Return True if approved, False if skipped

**Phase 2 processing** (`cli.py:process_movie_phase2()`):
1. Apply path mappings (NAS → local)
2. Find source language subtitle (reload from cache)
3. Load subtitle with UTF-8 (fallback to latin-1 encoding)
4. Load cached context from Phase 1 (warn if missing, continue with None)
5. Skip processing if `dry_run` mode enabled
6. **Translate** subtitles with `gpt-4o-mini` using cached context
7. Save target language subtitle output (with fallback to cache on write error)
8. Return success/failure status

**Interactive features** (`cli.py:select_movies_interactive()`):
- Displays rich table with movie info (title, year, missing subtitles)
- Accepts user input:
  - Comma-separated movie numbers (e.g., "1,3,5")
  - "all" to select all movies
  - "q" to quit
- Returns list of selected Movie objects

## Key Design Decisions

### Hybrid Service Tier Cost Optimization
- **gpt-5** with `service_tier="auto"` for analysis ensures high-quality context extraction
  - Handles multi-layer instructions (entity handling, conditional translations)
  - Processes comprehensive JSON style guides with complex rules
  - Strong multilingual understanding (English/Spanish/Finnish code-switching)
  - Standard tier for fast responses during interactive human review
- **gpt-5** with `service_tier="flex"` for translation reduces costs by 50%
  - Executes straightforward translation guided by comprehensive context
  - Maintains quality through detailed character/place/term mappings
  - Flex tier provides 50% discount on both input and output tokens
  - Automatic prompt caching with Flex provides 90% discount on cached tokens
  - Longer timeouts (900s vs 60s) accommodate Flex's slower response times
  - 429 "Resource Unavailable" errors are retried automatically

### Context-Aware Translation
The two-pass approach ensures:
- Character names handled consistently throughout the movie
- Recurring phrases and terminology maintain consistent translations
- Appropriate formality level (formal "te" vs informal "sinä") based on genre/tone
- Genre-appropriate idiom and expression handling
- Cultural reference localization

### Batch Processing
- Reduces API calls while maintaining context window limits
- Default batch size of 50 balances token usage and response quality
- Each batch receives full context from Pass 1
- Position markers ("Beginning of movie"/"End of movie") provide temporal context
- Progress indicator shows real-time translation status

### Error Handling
- **Missing mkvtoolnix**: Graceful error with installation instructions
- **Encoding issues**: Tries UTF-8, falls back to latin-1
- **Translation errors**: Preserves original text on batch failure
- **Path issues**: Falls back to cache directory if NAS write fails
- **Config missing**: Exits with helpful error message pointing to config.example.yml
- **Bazarr API errors**: Exits with HTTP error details
- **Cache loading errors**: Logs warning and proceeds with fresh analysis

## Dependencies

### Core packages (pyproject.toml)
- `httpx>=0.28.1`: HTTP client for Bazarr API
- `openai>=2.8.1`: OpenAI GPT API client
- `pysrt>=1.1.2`: SRT subtitle file parsing
- `pyyaml>=6.0.3`: YAML configuration parsing
- `rich>=14.2.0`: Console formatting and progress indicators

### Dev packages
- `pytest>=8.0.0`: Testing framework
- `pytest-cov>=4.1.0`: Code coverage

### External tools (required)
- `mkvtoolnix`: Provides `mkvmerge` (query MKV info) and `mkvextract` (extract subtitles)
  - Installation: `brew install mkvtoolnix` (macOS)
  - Debian/Ubuntu: `apt install mkvtoolnix`

### Python version
- Requires: 3.14+
- Managed by: `uv`

## Testing

### Test Coverage
Comprehensive test suite with 30 tests covering all modules:

**Core module tests** (`tests/core/`):
- `test_cache.py`: Cache path generation, roundtrip save/load, sanitization, error handling
- `test_config.py`: YAML loading, missing file handling, empty path mappings
- `test_models.py`: All dataclass definitions (Movie, SubtitleTrack, Config, TranslationContext)
- `test_utils.py`: CACHE_DIR creation, console availability

**Integration tests** (`tests/integrations/`):
- `test_bazarr.py`: Path mapping (exact matches, unmapped paths, multiple mappings, first match wins, empty list)

**Processing tests** (`tests/processing/`):
- `test_subtitles.py`: MKV file detection, external SRT patterns, subtitle not found scenarios

### Running tests
```bash
# Run all tests
uv run pytest -v

# Run specific test module
uv run pytest tests/core/test_config.py -v

# Run with coverage
uv run pytest --cov=subtrans --cov-report=html
```

### Test philosophy
- Fast unit tests for all core functionality
- No external API calls (mocked or stubbed)
- Comprehensive edge case coverage
- Clear test names describing what is tested

## Common Workflows

### First-time setup
```bash
# 1. Copy example config
cp config.example.yml config.yml

# 2. Edit with your Bazarr details
# Set: bazarr.url, bazarr.api_key
# Optionally: configure path_mappings, adjust models

# 3. Set OpenAI API key
export OPENAI_API_KEY=sk-...

# 4. Run the tool
uv run subtrans
```

### Translate specific movies
```bash
# Run and select movies interactively
uv run subtrans

# Example interaction:
# > Found 15 movies missing Finnish subtitles
# > Enter movie numbers: 1,3,5
#
# Phase 1: Context Analysis
# > Processing: The Matrix (1999)
# > [Shows context JSON]
# > Approve this context for translation? [Y/n/e/d]
# > y
#
# > Processing: Inception (2010)
# > [Shows context JSON]
# > Approve this context for translation? [Y/n/e/d]
# > e  (edit context)
# > [Opens editor, user edits character names]
# > Approve edited context for translation? [Y/n]
# > y
#
# > Processing: Interstellar (2014)
# > [Shows context JSON]
# > Approve this context for translation? [Y/n/e/d]
# > n  (skip this movie)
#
# > 2/3 movies approved for translation
#
# Phase 2: Translation
# > Translating: The Matrix (1999)
# > [Progress bar for translation batches]
# > Saved fi subtitles: /path/to/The.Matrix.1999.fi.srt
#
# > Translating: Inception (2010)
# > [Progress bar for translation batches]
# > Saved fi subtitles: /path/to/Inception.2010.fi.srt
#
# > Completed: 2/2 movies translated
```

### Batch extraction mode
```bash
# Extract and cache all subtitles without translation
# Useful for pre-populating cache, no OpenAI API key required
uv run subtrans --extract-only

# Example interaction:
# > Found 50 movies missing Finnish subtitles
# > Enter movie numbers: all
# > Extract-only mode - subtitle cached successfully
# > Completed: 50/50 movies processed

# Benefits:
# - Run overnight to populate cache for entire library
# - No OpenAI API costs during extraction
# - Faster translation runs later (subtitles already cached)
# - Can extract while on NAS network, translate offline later
```

### Debugging/development
```bash
# Dry run (no translation, just list movies)
# Set dry_run: true in config.yml
uv run subtrans

# Skip context analysis (faster, less consistent)
# Set skip_analysis: true in config.yml
uv run subtrans

# Save context for review
# Set save_context: true in config.yml
# Check ~/.cache/subtrans/ for *_context.json files
```

### Model selection
```bash
# Edit config.yml to change models:
openai:
  analysis_model: "gpt-4o"        # More capable, handles complex rules
  translation_model: "gpt-4o-mini"  # Cost-effective, context-guided
  batch_size: 50

# Or use same model for both passes:
openai:
  analysis_model: "gpt-4o"
  translation_model: "gpt-4o"  # Higher quality, higher cost
```

## Notes for Claude Code

### When modifying this project:
1. **Run tests after changes**: `uv run pytest -v`
2. **Check config schema**: If modifying Config dataclass, update `config.example.yml` and tests
3. **Cache awareness**: Understand that cache may contain stale data during development
4. **Two-model architecture**: Preserve separation between analysis (gpt-4o) and translation (gpt-4o-mini)
5. **Error handling**: Maintain graceful fallbacks for all external operations
6. **Progress indicators**: Use `rich` console for user-friendly output
7. **Type hints**: Maintain type annotations for all functions
8. **Documentation**: Update this file when making architectural changes

### Common modification patterns:
- **Adding new config option**: Update `Config` dataclass → `load_config()` → `config.example.yml` → tests
- **Changing translation logic**: Modify `translator.py` → verify with tests
- **Adding new subtitle source**: Extend `get_english_subtitle()` in `subtitles.py`
- **Modifying cache behavior**: Update `cache.py` functions
- **Changing Bazarr integration**: Modify `bazarr.py` functions

### Important constraints:
- **Single-user, private use**: No multi-tenancy, no production SaaS features needed
- **NAS-aware**: Path mapping is critical for SMB mount scenarios
- **Cache persistence**: Don't clear cache without user consent
- **Cost optimization**: Preserve two-model architecture for cost efficiency
- **UTF-8 encoding**: All output files must be UTF-8 (subtitle standard)
