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
