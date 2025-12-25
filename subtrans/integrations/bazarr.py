"""Bazarr API integration for fetching movies with missing subtitles."""

import sys

import httpx

from ..core.models import Movie
from ..core.utils import console


def get_wanted_movies(
    base_url: str, api_key: str, source_lang: str = "en", target_lang: str = "fi"
) -> list[Movie]:
    """
    Fetch movies missing target language subtitles from Bazarr.

    Returns all movies missing target language subtitles, regardless of whether
    they have source language subtitles tracked in Bazarr. The actual source
    subtitle check (including embedded MKV subtitles) happens during processing.

    Args:
        base_url: Bazarr server URL
        api_key: Bazarr API key
        source_lang: Source language code (ISO 639-1/2, default: "en")
        target_lang: Target language code (ISO 639-1/2, default: "fi")

    Returns:
        List of Movie objects with missing target language subtitles

    Raises:
        SystemExit: If API request fails
    """
    headers = {"X-API-KEY": api_key}

    # Get wanted movies (movies with missing subtitles)
    url = f"{base_url}/api/movies/wanted"

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        console.print(f"[red]Error fetching wanted movies: {e}[/red]")
        sys.exit(1)

    movies = []
    for item in data.get("data", []):
        # Check if target language is in the missing subtitles
        missing = item.get("missing_subtitles", [])
        missing_langs = [s.get("code2", s.get("code3", "")) for s in missing]

        # Check for both exact match and startswith (handles 2-letter and 3-letter codes)
        if any(
            lang == target_lang or lang.startswith(target_lang)
            for lang in missing_langs
        ):
            # Note: We no longer filter out movies based on source language availability
            # since many movies have embedded subtitles in MKV files that Bazarr doesn't track
            # The source subtitle check will happen during movie processing

            # Note: path will be empty here, we'll fetch it after user selection
            # Note: year will be 0 here, we'll fetch it along with path after selection
            movies.append(
                Movie(
                    radarr_id=item.get("radarrId"),
                    title=item.get("title", "Unknown"),
                    year=0,  # Will be populated along with path after selection
                    path="",  # Will be populated after selection
                    missing_subtitles=missing_langs,
                    existing_subtitles=item.get("subtitles", []),
                )
            )

    return movies


def populate_movie_path(movie: Movie, base_url: str, api_key: str) -> bool:
    """
    Fetch and populate the movie path from Bazarr API.

    Args:
        movie: Movie object to populate path for
        base_url: Bazarr server URL
        api_key: Bazarr API key

    Returns:
        True if path was successfully populated, False otherwise
    """
    headers = {"X-API-KEY": api_key}
    url = f"{base_url}/api/movies"

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(
                url, headers=headers, params={"radarrid": movie.radarr_id}
            )
            response.raise_for_status()
            data = response.json()

            # The API returns a list or dict, find the matching movie
            movies_list = []
            if isinstance(data, dict) and "data" in data:
                movies_list = data["data"]
            elif isinstance(data, list):
                movies_list = data

            for item in movies_list:
                if item.get("radarrId") == movie.radarr_id:
                    movie.path = item.get("path", "")
                    # Also populate year if it's missing (year=0)
                    if movie.year == 0 and item.get("year"):
                        movie.year = item.get("year")
                    if movie.path:
                        return True
                    else:
                        console.print(
                            f"[yellow]Warning: No path found for '{movie.title}'[/yellow]"
                        )
                        return False

            console.print(
                f"[yellow]Warning: Movie not found in API response for '{movie.title}'[/yellow]"
            )
            return False

    except Exception as e:
        console.print(f"[red]Failed to get path for '{movie.title}': {e}[/red]")
        return False


def apply_path_mapping(path: str, path_mappings: list[tuple[str, str]]) -> str:
    """
    Apply path mappings to translate NAS paths to local mount points.

    Args:
        path: Original path from Bazarr
        path_mappings: List of (from_path, to_path) tuples

    Returns:
        Mapped path or original path if no mapping matches
    """
    if not path_mappings:
        return path

    for from_path, to_path in path_mappings:
        if path.startswith(from_path):
            mapped = path.replace(from_path, to_path, 1)
            console.print(f"[dim]Path mapped: {path} -> {mapped}[/dim]")
            return mapped

    return path
