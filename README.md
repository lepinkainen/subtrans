# Subtitle Translator

Translates English subtitles to Finnish using OpenAI GPT models with context-aware two-pass translation.

## Features

- **Bazarr Integration**: Automatically finds movies missing Finnish subtitles
- **Context-Aware Translation**: Analyzes subtitle content to maintain consistency in character names, terminology, and tone
- **Two-Pass Approach**: First analyzes context, then translates with full context awareness
- **Path Mapping**: Maps NAS paths to local mount points for laptop/SMB usage
- **MKV Support**: Extracts embedded subtitle tracks from MKV files
- **Batch Processing**: Efficient API usage with configurable batch sizes

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
# Run with default config
uv run main.py

# Use custom config file
uv run main.py --config /path/to/config.yml
```

## Configuration

All settings are managed in `config.yml`:

- **bazarr**: Bazarr server URL and API key
- **openai**: Model selection and batch size
- **path_mappings**: Map NAS paths to local SMB mount points
- **translation**: Skip analysis, save context, dry run options

See `config.example.yml` for detailed configuration options.

## Path Mapping

When running from a laptop with NAS mounted via SMB, configure path mappings:

```yaml
path_mappings:
  - from: "/volume1/movies"
    to: "/Volumes/NAS/movies"
```

This maps Bazarr's NAS paths to your local mount points.

## How It Works

### Two-Pass Translation

**Pass 1: Context Analysis**
- Analyzes complete subtitle file
- Extracts character names, places, recurring terms
- Determines genre, tone, and formality level
- Saves context for consistent translation

**Pass 2: Batch Translation**
- Translates in batches (default: 50 subtitles per API call)
- Uses context from Pass 1 for consistency
- Maintains appropriate tone and formality throughout

### Subtitle Sources

The tool searches for English subtitles in this order:
1. External SRT files (*.en.srt, *.eng.srt, etc.)
2. Embedded MKV subtitle tracks (extracts text-based tracks only)

### Output

Translated subtitles are saved as `<movie_name>.fi.srt` in the same directory as the source video file.

## License

MIT
