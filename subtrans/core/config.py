"""Configuration loading and management."""

import os
import sys
from pathlib import Path

import yaml

from .models import Config
from .utils import console


def load_config(config_path: Path) -> Config:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to the YAML configuration file

    Returns:
        Config object with loaded settings

    Raises:
        SystemExit: If config file doesn't exist
    """
    if not config_path.exists():
        console.print(f"[red]Config file not found: {config_path}[/red]")
        console.print(
            "[yellow]Create config.yml from config.example.yml template[/yellow]"
        )
        sys.exit(1)

    with open(config_path) as f:
        data = yaml.safe_load(f)

    # Parse path mappings
    path_mappings = []
    for mapping in data.get("path_mappings", []):
        path_mappings.append((mapping["from"], mapping["to"]))

    # Strip trailing slashes from URL to avoid double slashes in API calls
    bazarr_url = data["bazarr"]["url"].rstrip("/")

    return Config(
        bazarr_url=bazarr_url,
        bazarr_api_key=data["bazarr"]["api_key"],
        openai_api_key=data["openai"].get(
            "api_key", os.environ.get("OPENAI_API_KEY", "")
        ),
        analysis_model=data["openai"]["analysis_model"],
        translation_model=data["openai"]["translation_model"],
        batch_size=data["openai"]["batch_size"],
        path_mappings=path_mappings,
        skip_analysis=data["translation"]["skip_analysis"],
        save_context=data["translation"]["save_context"],
        dry_run=data["translation"]["dry_run"],
        source_language=data.get("languages", {}).get("source", "en"),
        target_language=data.get("languages", {}).get("target", "fi"),
        validate_translation=data["translation"].get("validate_translation", True),
        min_translation_difference=data["translation"].get(
            "min_translation_difference", 0.8
        ),
        analysis_service_tier=data["openai"].get("analysis_service_tier", "auto"),
        translation_service_tier=data["openai"].get("translation_service_tier", "flex"),
        log_token_usage=data["translation"].get("log_token_usage", True),
        # Validation settings with defaults for backward compatibility
        min_subtitle_count=data.get("validation", {}).get("min_subtitle_count", 50),
        min_subtitle_file_size=data.get("validation", {}).get(
            "min_subtitle_file_size", 2048
        ),
        strict_validation=data.get("validation", {}).get("strict_validation", True),
        # Track selection behavior with defaults for backward compatibility
        interactive_track_selection=data.get("subtitle_selection", {}).get(
            "interactive_track_selection", True
        ),
        auto_select_tracks=data.get("subtitle_selection", {}).get(
            "auto_select_tracks", False
        ),
        # pysrt validation settings with defaults for backward compatibility
        validate_subtitles=data.get("pysrt_validation", {}).get(
            "validate_subtitles", True
        ),
        min_duration_ms=data.get("pysrt_validation", {}).get("min_duration_ms", 500),
        max_duration_secs=data.get("pysrt_validation", {}).get(
            "max_duration_secs", 10.0
        ),
        min_text_length=data.get("pysrt_validation", {}).get("min_text_length", 2),
        max_text_length=data.get("pysrt_validation", {}).get("max_text_length", 500),
        # Overlap fixing settings with defaults for backward compatibility
        fix_overlaps=data.get("output", {}).get("fix_overlaps", True),
        overlap_buffer_ms=data.get("output", {}).get("overlap_buffer_ms", 20),
    )
