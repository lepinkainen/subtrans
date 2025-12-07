"""Configuration loading and management."""

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

    return Config(
        bazarr_url=data["bazarr"]["url"],
        bazarr_api_key=data["bazarr"]["api_key"],
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
    )
