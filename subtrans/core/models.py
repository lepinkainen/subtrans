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
    analysis_model: str      # Model for Pass 1: Context analysis
    translation_model: str   # Model for Pass 2: Translation
    batch_size: int
    path_mappings: list[tuple[str, str]]
    skip_analysis: bool
    save_context: bool
    dry_run: bool


@dataclass
class TranslationContext:
    """Context extracted from first-pass analysis."""

    characters: dict[str, str]  # English name -> Finnish handling
    places: dict[str, str]  # English place -> Finnish handling
    terms: dict[str, str]  # Recurring terms/phrases -> Finnish
    genre: str
    tone: str  # formal, informal, mixed
    formality: str  # te (formal) or sinä (informal)
    style_notes: str
    raw_json: dict
