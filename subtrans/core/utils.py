"""Shared utilities and constants."""

from pathlib import Path
from rich.console import Console

# Global console instance for formatted output
console = Console()

# Cache directory for extracted subtitles and context files
CACHE_DIR = Path.home() / ".cache" / "subtrans"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
