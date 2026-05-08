"""Data models for subtrans application."""

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

ServiceTier = Literal["auto", "default", "flex", "scale", "priority"]


@runtime_checkable
class MediaItem(Protocol):
    """Protocol defining shared interface for all media types (movies, episodes)."""

    @property
    def display_title(self) -> str:
        """Human-readable title for display (e.g., 'Matrix (1999)' or 'Breaking Bad S01E05')."""
        ...

    @property
    def display_subtitle(self) -> str:
        """Secondary info for display (e.g., 'Pilot - Missing: fi')."""
        ...

    @property
    def file_path(self) -> str:
        """Path to media file."""
        ...

    @property
    def cache_key(self) -> tuple:
        """Unique tuple for cache lookups (variant-specific shape)."""
        ...

    @property
    def analyze_title(self) -> str:
        """Title to feed to analysis prompts and token-logger labels.

        Movies use the bare title; episodes use the full SxxExx display so the
        per-episode log entries remain distinguishable.
        """
        ...

    @property
    def analyze_year(self) -> int:
        """Year for token-logger / pricing context (movie year or series year)."""
        ...

    path: str  # Mutable path field (can be updated by path mapping)
    missing_subtitles: list[str]
    existing_subtitles: list[dict]


@dataclass
class Movie:
    """Represents a movie with subtitle metadata."""

    radarr_id: int
    title: str
    year: int
    path: str
    missing_subtitles: list[str]
    existing_subtitles: list[dict]

    @property
    def display_title(self) -> str:
        """Human-readable title for display."""
        return f"{self.title} ({self.year})"

    @property
    def display_subtitle(self) -> str:
        """Secondary info showing missing subtitles."""
        return f"Missing: {', '.join(self.missing_subtitles)}"

    @property
    def file_path(self) -> str:
        """Path to movie file."""
        return self.path

    @property
    def cache_key(self) -> tuple[str, int]:
        """Unique cache key based on title and year."""
        return (self.title, self.year)

    @property
    def analyze_title(self) -> str:
        return self.title

    @property
    def analyze_year(self) -> int:
        return self.year


@dataclass
class Episode:
    """Represents a TV episode with subtitle metadata."""

    sonarr_id: int
    series_name: str
    season_number: int
    episode_number: int
    episode_title: str
    path: str
    missing_subtitles: list[str]
    existing_subtitles: list[dict]
    series_year: int = 0  # Year series started (for cache key)
    sonarr_series_id: int = 0  # Series ID for API lookups

    @property
    def display_title(self) -> str:
        """Human-readable title for display."""
        return f"{self.series_name} S{self.season_number:02d}E{self.episode_number:02d}"

    @property
    def display_subtitle(self) -> str:
        """Secondary info showing episode title and missing subtitles."""
        return f"{self.episode_title} - Missing: {', '.join(self.missing_subtitles)}"

    @property
    def file_path(self) -> str:
        """Path to episode file."""
        return self.path

    @property
    def cache_key(self) -> tuple[str, int, int]:
        """Unique cache key based on series, season, and episode."""
        return (self.series_name, self.season_number, self.episode_number)

    @property
    def series_cache_key(self) -> tuple[str, int]:
        """Cache key for series-wide context (shared across all episodes)."""
        return (self.series_name, self.series_year)

    @property
    def analyze_title(self) -> str:
        return self.display_title

    @property
    def analyze_year(self) -> int:
        return self.series_year


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
    openai_api_key: str  # OpenAI API key
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
    # Service tier for OpenAI API pricing
    analysis_service_tier: ServiceTier = (
        "auto"  # Standard pricing for Pass 1 (interactive)
    )
    translation_service_tier: ServiceTier = (
        "flex"  # Flex pricing for Pass 2 (50% discount)
    )
    # Subtitle validation settings
    min_subtitle_count: int = 50  # Minimum entries for valid subtitle
    min_subtitle_file_size: int = 2048  # Minimum file size (2KB)
    strict_validation: bool = True  # Hard error vs warning on validation failure
    # Track selection behavior
    interactive_track_selection: bool = True  # Show track table and prompt user
    auto_select_tracks: bool = False  # Skip prompts, use automatic selection
    # pysrt validation settings (comprehensive subtitle checks)
    validate_subtitles: bool = True  # Enable pysrt subtitle validation
    min_duration_ms: float = 500  # Minimum subtitle duration
    max_duration_secs: float = 10.0  # Maximum subtitle duration
    min_text_length: int = 2  # Minimum text length per subtitle
    max_text_length: int = 500  # Maximum text length per subtitle
    # Overlap fixing settings
    fix_overlaps: bool = True  # Fix overlapping subtitles after translation
    overlap_buffer_ms: int = 20  # Minimum gap between subtitles


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


class ContextResponse(BaseModel):
    """Pydantic schema for the JSON returned by the Pass-1 analysis prompt.

    Lives at the OpenAI boundary; convert to ``TranslationContext`` (the
    internal carrier) via ``to_translation_context``. Field-name drift between
    the prompt and consumers becomes a hard error here, not silent defaults.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    characters: dict[str, str] = Field(default_factory=dict)
    places: dict[str, str] = Field(default_factory=dict)
    terms: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("terms", "recurring_terms"),
    )
    genre: str = "unknown"
    tone: str = "mixed"
    formality: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "formality", "formality_recommendation", "formality_guidance"
        ),
    )
    style_notes: str = ""
    domains: list[str] = Field(default_factory=list)
    domain_glossaries: dict[str, dict[str, str]] = Field(default_factory=dict)

    def to_translation_context(self, raw_json: dict) -> TranslationContext:
        """Build a `TranslationContext` from this validated payload."""
        return TranslationContext(
            characters=self.characters,
            places=self.places,
            terms=self.terms,
            genre=self.genre,
            tone=self.tone,
            formality=self.formality,
            style_notes=self.style_notes,
            domains=self.domains,
            domain_glossaries=self.domain_glossaries,
            raw_json=raw_json,
        )
