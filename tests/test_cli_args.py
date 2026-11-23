"""Tests for CLI argument parsing and per-run overrides."""

import pytest

from subtrans.cli import _apply_cli_overrides
from subtrans.cli_args import parse_arguments
from subtrans.core.models import Config


def _config() -> Config:
    return Config(
        bazarr_url="http://bazarr",
        bazarr_api_key="key",
        openai_api_key="",
        analysis_model="gpt-test",
        translation_model="gpt-test",
        batch_size=50,
        path_mappings=[],
        skip_analysis=False,
        save_context=False,
        dry_run=False,
    )


def test_translation_tier_defaults_to_none():
    assert parse_arguments([]).translation_tier is None


def test_translation_tier_accepts_known_tier():
    assert parse_arguments(["--translation-tier", "auto"]).translation_tier == "auto"


def test_translation_tier_rejects_unknown_tier():
    with pytest.raises(SystemExit):
        parse_arguments(["--translation-tier", "cheap"])


def test_translation_tier_overrides_config_only():
    config = _config()
    assert config.translation_service_tier == "flex"

    _apply_cli_overrides(config, parse_arguments(["--translation-tier", "priority"]))

    assert config.translation_service_tier == "priority"
    assert config.analysis_service_tier == "auto"


def test_no_override_keeps_config_tier():
    config = _config()
    _apply_cli_overrides(config, parse_arguments([]))
    assert config.translation_service_tier == "flex"


def test_tier_overrides_both_passes():
    config = _config()
    _apply_cli_overrides(config, parse_arguments(["--tier", "default"]))
    assert config.analysis_service_tier == "default"
    assert config.translation_service_tier == "default"


def test_analysis_tier_overrides_pass1_only():
    config = _config()
    _apply_cli_overrides(config, parse_arguments(["--analysis-tier", "default"]))
    assert config.analysis_service_tier == "default"
    assert config.translation_service_tier == "flex"


def test_per_pass_flag_wins_over_tier():
    config = _config()
    args = parse_arguments(["--tier", "default", "--translation-tier", "flex"])
    _apply_cli_overrides(config, args)
    assert config.analysis_service_tier == "default"
    assert config.translation_service_tier == "flex"
