"""Data models for subtrans application."""

from dataclasses import dataclass


@dataclass
class Movie:
    """Represents a movie with subtitle metadata."""

    radarr_id: int
    title: str
    year: int
    path: str
    missing_subtitles: list[str]
    existing_subtitles: list[dict]


@dataclass
class SubtitleTrack:
    """Represents a subtitle track from an MKV file."""

    track_id: int
    language: str
    name: str
    codec: str
    forced: bool = False  # Whether this is a forced subtitle track
    sdh: bool = False  # Whether this is SDH (subtitles for deaf/hard of hearing)
    entry_count: int = 0  # Number of subtitle entries (from num_index_entries)


@dataclass
class Config:
    """Application configuration."""

    bazarr_url: str
    bazarr_api_key: str
    analysis_model: str  # Model for Pass 1: Context analysis
    translation_model: str  # Model for Pass 2: Translation
    batch_size: int
    path_mappings: list[tuple[str, str]]
    skip_analysis: bool
    save_context: bool
    dry_run: bool
    source_language: str = "en"  # ISO 639-1/2 code for source subtitle language
    target_language: str = "fi"  # ISO 639-1/2 code for target translation language
    validate_translation: bool = (
        True  # Check if translations are sufficiently different
    )
    min_translation_difference: float = 0.8  # Minimum difference ratio (0.0-1.0)
    log_token_usage: bool = True  # Log API token usage to file for cost tracking
    # Service tier for OpenAI API pricing: "auto", "flex", "default", "priority"
    analysis_service_tier: str = "auto"  # Standard pricing for Pass 1 (interactive)
    translation_service_tier: str = "flex"  # Flex pricing for Pass 2 (50% discount)
    # Subtitle validation settings
    min_subtitle_count: int = 50  # Minimum entries for valid subtitle
    min_subtitle_file_size: int = 2048  # Minimum file size (2KB)
    strict_validation: bool = True  # Hard error vs warning on validation failure
    # Track selection behavior
    interactive_track_selection: bool = True  # Show track table and prompt user
    auto_select_tracks: bool = False  # Skip prompts, use automatic selection


@dataclass
class TranslationContext:
    """Context extracted from first-pass analysis."""

    characters: dict[str, str]  # Source name -> Target language handling
    places: dict[str, str]  # Source place -> Target language handling
    terms: dict[str, str]  # Recurring terms/phrases -> Target translation
    genre: str
    tone: str  # formal, informal, mixed
    formality: (
        str | None
    )  # Language-specific formality guidance (e.g., "te"/"sinä" for Finnish)
    style_notes: str
    domains: list[
        str
    ]  # Specialized semantic domains (e.g., "police_intelligence", "medical")
    domain_glossaries: dict[str, dict[str, str]]  # Domain-specific terminology mappings
    raw_json: dict
