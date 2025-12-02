"""Tests for core.config module."""

from pathlib import Path


def test_load_config_success(tmp_path):
    """Should load valid YAML config."""
    from subtrans.core.config import load_config

    config_file = tmp_path / "test_config.yml"
    config_file.write_text("""
bazarr:
  url: "http://test:6767"
  api_key: "test_key"
openai:
  model: "gpt-4"
  batch_size: 50
translation:
  skip_analysis: false
  save_context: true
  dry_run: false
path_mappings:
  - from: "/volume1/movies"
    to: "/mnt/movies"
""")

    config = load_config(config_file)
    assert config.bazarr_url == "http://test:6767"
    assert config.bazarr_api_key == "test_key"
    assert config.openai_model == "gpt-4"
    assert config.batch_size == 50
    assert config.path_mappings == [("/volume1/movies", "/mnt/movies")]
    assert config.skip_analysis is False
    assert config.save_context is True
    assert config.dry_run is False


def test_load_config_missing_file():
    """Should exit on missing config file."""
    from subtrans.core.config import load_config
    import pytest

    with pytest.raises(SystemExit):
        load_config(Path("/nonexistent/config.yml"))


def test_load_config_empty_path_mappings(tmp_path):
    """Should handle empty path mappings."""
    from subtrans.core.config import load_config

    config_file = tmp_path / "test_config.yml"
    config_file.write_text("""
bazarr:
  url: "http://test:6767"
  api_key: "test_key"
openai:
  model: "gpt-4"
  batch_size: 50
translation:
  skip_analysis: false
  save_context: true
  dry_run: false
path_mappings: []
""")

    config = load_config(config_file)
    assert config.path_mappings == []
