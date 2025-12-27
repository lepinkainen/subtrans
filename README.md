# Subtitle Translator

Translates subtitles between languages using OpenAI GPT models with context-aware two-pass translation.

## Features

- **Bazarr Integration**: Automatically finds movies and tv-series that are missing subtitles in the configured target language
- **Two-Pass Approach**: First analyzes context, then translates with full context awareness
- **Context-Aware Translation**: Analyzes subtitle content to maintain consistency in character names, terminology, and tone
- **Path Mapping**: Maps NAS paths to local mount points for laptop/SMB usage
- **MKV Support**: Extracts embedded subtitle tracks from MKV files
- **Batch Processing**: Efficient API usage with configurable batch sizes, uses OpenAI's flex pricing tier for cost savings (50% discount)

In my experience a two-pass approach significantly improves translation quality, especially for media with recurring characters, specific terminology, or unique tones. Using the flex pricing costs about $1 per movie with GPT-5. Other models are cheaper, but the quality may vary from OK to "what the fuck did I just read". At least the first context pass should be done with a "smart" model.

## How It Works

### Two-Pass Translation

#### Pass 1: Context Analysis**

- Analyzes complete subtitle file
- Extracts character names, places, recurring terms
- Determines genre, tone, and formality level
- Saves context for consistent translation
- If there are any errors, this is the place to correct them

#### Pass 2: Batch Translation**

- Translates in batches (default: 50 subtitles per API call)
- Uses context from Pass 1 for consistency
- Maintains appropriate tone and formality throughout

### Subtitle Sources

The tool searches for English subtitles in this order:

1. External SRT files (*.en.srt,*.eng.srt, etc.)
2. Embedded MKV subtitle tracks (extracts text-based tracks only)

### Output

Translated subtitles are saved as `<movie_name>.fi.srt` in the same directory as the source video file.

**Fallback**: If writing to the media directory fails (e.g., NAS permission errors), subtitles are saved to `~/.cache/subtrans/<movie_name>_<year>.<target>.srt` instead. Check the console output for the actual save location.

## Setup

1. **Install dependencies**:

   ```bash
   uv sync
   ```

2. **Install mkvtoolnix** (for MKV subtitle extraction):

   ```bash
   # macOS
   brew install mkvtoolnix

   # Ubuntu/Debian
   apt install mkvtoolnix
   ```

3. **Create configuration file**:

   ```bash
   cp config.example.yml config.yml
   ```

4. **Edit `config.yml`**:
   - Set your Bazarr URL and API key
   - Configure path mappings if needed
   - Adjust translation options

5. **Set OpenAI API key**:

   ```bash
   export OPENAI_API_KEY=your_api_key_here
   ```

## Usage

```bash
# Default is for movies
uv run subtrans
# Run for TV series
uv run subtrans --series
```

**Note**: Movies missing the target language subtitles are displayed for selection. During processing (Phase 1), movies without source language subtitles (default English) are skipped with a console message. This includes embedded MKV subtitles that Bazarr may not track.

## Configuration

All settings are managed in `config.yml`:

- **bazarr**: Bazarr server URL and API key
- **openai**: Model selection and batch size
- **path_mappings**: Map NAS paths to local SMB mount points
- **translation**: Skip analysis, save context, dry run options

See `config.example.yml` for detailed configuration options.

### Configuration Options

#### Validation Settings

```yaml
validation:
  min_subtitle_count: 50          # Minimum expected subtitle entries, adjust if you're watching artsy stuff where people don't talk much
  min_subtitle_file_size: 2048    # Minimum file size in bytes (detects corrupted files)
  strict_validation: true         # Require user confirmation for low-quality subtitles
```

#### Subtitle Track Selection

```yaml
subtitle_selection:
  interactive_track_selection: true   # Prompt user to select track when multiple found
  auto_select_tracks: false           # Skip prompts and use automatic selection
```

#### Language Configuration

```yaml
languages:
  source: en    # Source language code (English)
  target: fi    # Target language code (Finnish)
```

Supported language codes: ISO 639-1 (2-letter codes like `en`, `fi`, `es`, `de`)

## Path Mapping

When running from a laptop with NAS mounted via SMB, configure path mappings from bazarr to local mount points:

```yaml
path_mappings:
  - from: "/volume1/movies"
    to: "/Volumes/NAS/movies"
```
