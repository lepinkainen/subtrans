"""Bazarr API integration for fetching movies and episodes with missing subtitles."""

import sys
from collections import defaultdict

import httpx

from ..core.models import Episode, Movie
from ..core.utils import console
from .bazarr_models import (
    BazarrEpisodeDetail,
    BazarrListResponse,
    BazarrMovieDetail,
    BazarrSubtitle,
    BazarrWantedEpisode,
    BazarrWantedMovie,
)


def _missing_lang_codes(missing: list[BazarrSubtitle]) -> list[str]:
    """Flatten Bazarr subtitle records to a list of language code strings.

    Prefers ``code2`` over ``code3``; empty if neither present. The match logic
    in `_target_in_missing` tolerates either form.
    """
    return [s.code2 or s.code3 or "" for s in missing]


def _target_in_missing(missing_codes: list[str], target_lang: str) -> bool:
    """True if ``target_lang`` appears (exact or as prefix) in ``missing_codes``."""
    return any(
        code == target_lang or code.startswith(target_lang) for code in missing_codes
    )


def _subtitles_to_dicts(subs: list[BazarrSubtitle]) -> list[dict]:
    """Serialize parsed BazarrSubtitle records back to plain dicts.

    Internal ``Movie.existing_subtitles`` is typed ``list[dict]`` and consumed
    by code that doesn't depend on a specific schema.
    """
    return [s.model_dump(exclude_none=True) for s in subs]


def get_wanted_movies(
    base_url: str, api_key: str, source_lang: str = "en", target_lang: str = "fi"
) -> list[Movie]:
    """Fetch movies missing target language subtitles from Bazarr.

    Returns all movies missing target language subtitles, regardless of whether
    they have source language subtitles tracked in Bazarr. Source-subtitle
    presence is rechecked during processing (embedded MKV tracks count too).

    Raises:
        SystemExit: If API request fails.
    """
    headers = {"X-API-KEY": api_key}
    url = f"{base_url}/api/movies/wanted"

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as e:
        console.print(f"[red]Error fetching wanted movies: {e}[/red]")
        sys.exit(1)

    parsed = BazarrListResponse[BazarrWantedMovie].model_validate(payload)

    movies: list[Movie] = []
    for item in parsed.data:
        missing_codes = _missing_lang_codes(item.missing_subtitles)
        if not _target_in_missing(missing_codes, target_lang):
            continue
        movies.append(
            Movie(
                radarr_id=item.radarr_id,
                title=item.title,
                year=item.year,
                path=item.path,
                missing_subtitles=missing_codes,
                existing_subtitles=_subtitles_to_dicts(item.subtitles),
            )
        )

    return movies


def populate_movie_path(movie: Movie, base_url: str, api_key: str) -> bool:
    """Populate ``movie.path`` and ``movie.year`` from Bazarr's movie detail API.

    Returns True on success.
    """
    headers = {"X-API-KEY": api_key}
    url = f"{base_url}/api/movies"

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(
                url, headers=headers, params={"radarrid": movie.radarr_id}
            )
            response.raise_for_status()
            parsed = BazarrListResponse[BazarrMovieDetail].model_validate(
                response.json()
            )
    except Exception as e:
        console.print(f"[red]Failed to get path for '{movie.title}': {e}[/red]")
        return False

    for item in parsed.data:
        if item.radarr_id != movie.radarr_id:
            continue
        movie.path = item.path
        if movie.year == 0 and item.year:
            movie.year = item.year
        if movie.path:
            return True
        console.print(f"[yellow]Warning: No path found for '{movie.title}'[/yellow]")
        return False

    console.print(
        f"[yellow]Warning: Movie not found in API response for '{movie.title}'[/yellow]"
    )
    return False


def get_wanted_episodes(
    base_url: str, api_key: str, source_lang: str = "en", target_lang: str = "fi"
) -> list[Episode]:
    """Fetch episodes missing target language subtitles from Bazarr.

    Same source-subtitle policy as `get_wanted_movies`.

    Raises:
        SystemExit: If API request fails.
    """
    headers = {"X-API-KEY": api_key}
    url = f"{base_url}/api/episodes/wanted"

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as e:
        console.print(f"[red]Error fetching wanted episodes: {e}[/red]")
        sys.exit(1)

    parsed = BazarrListResponse[BazarrWantedEpisode].model_validate(payload)

    episodes: list[Episode] = []
    for item in parsed.data:
        missing_codes = _missing_lang_codes(item.missing_subtitles)
        if not _target_in_missing(missing_codes, target_lang):
            continue
        season, ep = item.season_episode
        episodes.append(
            Episode(
                sonarr_id=item.sonarr_id,
                series_name=item.series_title,
                season_number=season,
                episode_number=ep,
                episode_title=item.episode_title,
                path=item.path,
                missing_subtitles=missing_codes,
                existing_subtitles=_subtitles_to_dicts(item.subtitles),
                series_year=item.year,
                sonarr_series_id=item.sonarr_series_id,
            )
        )

    return episodes


def _fetch_episode_details_for_series(
    series_id: int, base_url: str, api_key: str
) -> list[BazarrEpisodeDetail]:
    """Fetch all episode details for a single Sonarr series ID.

    Bazarr requires the ``seriesid[]`` bracket syntax.
    """
    url = f"{base_url}/api/episodes"
    headers = {"X-API-KEY": api_key}
    with httpx.Client(timeout=30) as client:
        response = client.get(url, headers=headers, params={"seriesid[]": series_id})
        response.raise_for_status()
        payload = response.json()
    return BazarrListResponse[BazarrEpisodeDetail].model_validate(payload).data


def _apply_episode_detail(episode: Episode, detail: BazarrEpisodeDetail) -> bool:
    """Copy fields from a BazarrEpisodeDetail into an Episode in-place.

    Returns True if a real path was populated.
    """
    episode.path = detail.path
    if detail.season:
        episode.season_number = detail.season
    if detail.episode:
        episode.episode_number = detail.episode
    return bool(episode.path)


def populate_episode_path(episode: Episode, base_url: str, api_key: str) -> bool:
    """Populate a single episode via its series detail call.

    Kept for backwards compatibility with callers that operate one-at-a-time;
    bulk callers should prefer ``populate_episode_paths_bulk``.
    """
    try:
        details = _fetch_episode_details_for_series(
            episode.sonarr_series_id, base_url, api_key
        )
    except Exception as e:
        console.print(
            f"[yellow]Warning: Could not fetch episode details for "
            f"'{episode.display_title}': {e}[/yellow]"
        )
        return True

    for detail in details:
        if detail.sonarr_id != episode.sonarr_id:
            continue
        if _apply_episode_detail(episode, detail):
            return True
        console.print(
            f"[yellow]Warning: No path found for '{episode.display_title}'[/yellow]"
        )
        return False

    console.print(
        f"[yellow]Warning: Episode path not available from Bazarr API for "
        f"'{episode.display_title}'[/yellow]"
    )
    console.print(
        "[dim]  Suggestion: Run 'Update all' or 'Full sync' in Bazarr to refresh "
        "episode data[/dim]"
    )
    return True


def populate_episode_paths_bulk(
    episodes: list[Episode], base_url: str, api_key: str
) -> None:
    """Populate paths for many episodes with one HTTP call per series.

    Bazarr's ``/api/episodes?seriesid[]=N`` returns every episode for the
    series, so per-episode iteration is wasteful when many episodes from the
    same series are selected.
    """
    by_series: dict[int, list[Episode]] = defaultdict(list)
    for ep in episodes:
        by_series[ep.sonarr_series_id].append(ep)

    for series_id, group in by_series.items():
        try:
            details = _fetch_episode_details_for_series(series_id, base_url, api_key)
        except Exception as e:
            for ep in group:
                console.print(
                    f"[yellow]Warning: Could not fetch episode details for "
                    f"'{ep.display_title}': {e}[/yellow]"
                )
            continue

        details_by_id = {d.sonarr_id: d for d in details}
        for ep in group:
            detail = details_by_id.get(ep.sonarr_id)
            if detail is None:
                console.print(
                    f"[yellow]Warning: Episode path not available from Bazarr API "
                    f"for '{ep.display_title}'[/yellow]"
                )
                console.print(
                    "[dim]  Suggestion: Run 'Update all' or 'Full sync' in Bazarr to "
                    "refresh episode data[/dim]"
                )
                continue
            if not _apply_episode_detail(ep, detail):
                console.print(
                    f"[yellow]Warning: No path found for '{ep.display_title}'[/yellow]"
                )


def apply_path_mapping(path: str, path_mappings: list[tuple[str, str]]) -> str:
    """Translate a NAS path to its local mount via the first matching prefix."""
    if not path_mappings:
        return path

    for from_path, to_path in path_mappings:
        if path.startswith(from_path):
            mapped = path.replace(from_path, to_path, 1)
            console.print(f"[dim]Path mapped: {path} -> {mapped}[/dim]")
            return mapped

    return path
