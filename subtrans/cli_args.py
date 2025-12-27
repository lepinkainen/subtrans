"""Command-line argument parsing for subtrans."""

import argparse
from pathlib import Path


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments for subtrans.

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Translate movie subtitles between languages using OpenAI"
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=Path("config.yml"),
        help="Path to config file (default: config.yml)",
    )
    parser.add_argument(
        "--extract-only",
        "-e",
        action="store_true",
        help="Extract and cache subtitles only (no translation)",
    )
    parser.add_argument(
        "--legacy-selection",
        action="store_true",
        help="Use legacy numbered selection instead of fzf-style interface",
    )
    parser.add_argument(
        "--force-fzf",
        action="store_true",
        help="Force fzf-style interface even if terminal detection fails",
    )
    parser.add_argument(
        "--stats",
        "-s",
        action="store_true",
        help="Display token usage statistics and costs, then exit",
    )
    parser.add_argument(
        "--movie",
        "-m",
        type=str,
        help="Filter statistics by movie title (use with --stats)",
    )
    parser.add_argument(
        "--series",
        action="store_true",
        help="Enable episode mode (translate TV episodes instead of movies)",
    )
    parser.add_argument(
        "--select",
        type=str,
        metavar="PATTERN",
        help="Select items matching glob pattern (non-interactive, case-insensitive)",
    )

    return parser.parse_args()
