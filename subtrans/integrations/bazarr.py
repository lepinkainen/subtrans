"""Bazarr API integration for fetching movies and episodes with missing subtitles."""

import sys

import httpx

from ..core.models import Movie, Episode
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


def get_wanted_episodes(
    base_url: str, api_key: str, source_lang: str = "en", target_lang: str = "fi"
) -> list[Episode]:
    """
    Fetch episodes missing target language subtitles from Bazarr.

    Returns all episodes missing target language subtitles, regardless of whether
    they have source language subtitles tracked in Bazarr. The actual source
    subtitle check (including embedded MKV subtitles) happens during processing.

    Args:
        base_url: Bazarr server URL
        api_key: Bazarr API key
        source_lang: Source language code (ISO 639-1/2, default: "en")
        target_lang: Target language code (ISO 639-1/2, default: "fi")

    Returns:
        List of Episode objects with missing target language subtitles

    Raises:
        SystemExit: If API request fails
    """
    headers = {"X-API-KEY": api_key}

    # Get wanted episodes (episodes with missing subtitles)
    url = f"{base_url}/api/episodes/wanted"

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        console.print(f"[red]Error fetching wanted episodes: {e}[/red]")
        sys.exit(1)

    episodes = []
    for item in data.get("data", []):
        # Check if target language is in the missing subtitles
        missing = item.get("missing_subtitles", [])
        missing_langs = [s.get("code2", s.get("code3", "")) for s in missing]

        # Check for both exact match and startswith (handles 2-letter and 3-letter codes)
        if any(
            lang == target_lang or lang.startswith(target_lang)
            for lang in missing_langs
        ):
            # Note: We no longer filter out episodes based on source language availability
            # since many episodes have embedded subtitles in MKV files that Bazarr doesn't track
            # The source subtitle check will happen during episode processing

            # Parse episode_number which is in "SxE" format (e.g., "1x1", "2x15")
            episode_num_str = item.get("episode_number", "0x0")
            season_num = 0
            ep_num = 0
            if "x" in episode_num_str:
                parts = episode_num_str.split("x", 1)
                try:
                    season_num = int(parts[0])
                    ep_num = int(parts[1])
                except (ValueError, IndexError):
                    pass

            # Try to get path and year from wanted API response if available
            # If not available, they'll be populated after user selection via populate_episode_path
            episodes.append(
                Episode(
                    sonarr_id=item.get("sonarrEpisodeId", 0),
                    series_name=item.get("seriesTitle", "Unknown"),
                    season_number=season_num,
                    episode_number=ep_num,
                    episode_title=item.get("episodeTitle", ""),
                    path=item.get("path", ""),  # Try to get path from wanted API
                    missing_subtitles=missing_langs,
                    existing_subtitles=item.get("subtitles", []),
                    series_year=item.get("year", 0),  # Try to get year from wanted API
                    sonarr_series_id=item.get("sonarrSeriesId", 0),  # Store series ID for API lookups
                )
            )

    return episodes


def populate_episode_path(episode: Episode, base_url: str, api_key: str) -> bool:
    """
    Fetch and populate the episode path from Bazarr API.

    Uses the series ID to query for all episodes in the series, then finds
    the matching episode by sonarrEpisodeId.

    Args:
        episode: Episode object to populate path for
        base_url: Bazarr server URL
        api_key: Bazarr API key

    Returns:
        True if path was successfully populated, False otherwise
    """
    headers = {"X-API-KEY": api_key}

    # Query episodes by series ID using correct bracket notation
    # Bazarr API requires seriesid[] parameter format
    url = f"{base_url}/api/episodes"

    try:
        with httpx.Client(timeout=30) as client:
            # Use seriesid[] parameter to get all episodes for this series
            params = {"seriesid[]": episode.sonarr_series_id}
            response = client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            # The API returns {"data": [...]} structure
            episodes_list = []
            if isinstance(data, dict) and "data" in data:
                episodes_list = data["data"]
            elif isinstance(data, list):
                episodes_list = data

            for item in episodes_list:
                if item.get("sonarrEpisodeId") == episode.sonarr_id:
                    episode.path = item.get("path", "")
                    # Update season/episode numbers from the detailed API response
                    # (the wanted API returns "1x1" format which we parse, but this is authoritative)
                    if item.get("season"):
                        episode.season_number = item.get("season")
                    if item.get("episode"):
                        episode.episode_number = item.get("episode")
                    if episode.path:
                        return True
                    else:
                        console.print(
                            f"[yellow]Warning: No path found for '{episode.display_title}'[/yellow]"
                        )
                        return False

            # If we got here, episode wasn't found in the list
            # This is expected for wanted episodes - they might not be in the main episodes list
            console.print(
                f"[yellow]Warning: Episode path not available from Bazarr API for '{episode.display_title}'[/yellow]"
            )
            console.print(
                "[dim]  Suggestion: Run 'Update all' or 'Full sync' in Bazarr to refresh episode data[/dim]"
            )
            return True  # Not having a path isn't a fatal error - processing will handle it

    except Exception as e:
        console.print(
            f"[yellow]Warning: Could not fetch episode details for '{episode.display_title}': {e}[/yellow]"
        )
        # Return True to continue processing - we'll try to find subtitles anyway
        return True


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
