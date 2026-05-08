"""Pydantic models for Bazarr API responses.

These models live at the network boundary. Internal `Movie` / `Episode`
dataclasses (in `core.models`) are populated from these after validation.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.utils import console


class BazarrSubtitle(BaseModel):
    """Subtitle entry from Bazarr (existing or missing)."""

    model_config = ConfigDict(extra="ignore")

    code2: str | None = None
    code3: str | None = None
    language: str | None = None
    forced: bool = False
    hi: bool = False
    path: str | None = None


class BazarrWantedMovie(BaseModel):
    """An entry from /api/movies/wanted."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    radarr_id: int = Field(alias="radarrId")
    title: str = "Unknown"
    subtitles: list[BazarrSubtitle] = Field(default_factory=list)
    missing_subtitles: list[BazarrSubtitle] = Field(default_factory=list)
    path: str = ""
    year: int = 0


class BazarrWantedEpisode(BaseModel):
    """An entry from /api/episodes/wanted."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    sonarr_id: int = Field(alias="sonarrEpisodeId", default=0)
    sonarr_series_id: int = Field(alias="sonarrSeriesId", default=0)
    series_title: str = Field(alias="seriesTitle", default="Unknown")
    episode_title: str = Field(alias="episodeTitle", default="")
    episode_number: str = "0x0"
    subtitles: list[BazarrSubtitle] = Field(default_factory=list)
    missing_subtitles: list[BazarrSubtitle] = Field(default_factory=list)
    path: str = ""
    year: int = 0

    @property
    def season_episode(self) -> tuple[int, int]:
        """Parse the 'SxE' wanted-API string into (season, episode).

        Logs once on parse failure so the existing 'S00E00 may indicate Bazarr
        sync issues' warning has a paper trail. Returns (0, 0) on failure.
        """
        raw = self.episode_number
        if "x" in raw:
            head, _, tail = raw.partition("x")
            try:
                return int(head), int(tail)
            except ValueError:
                pass
        console.print(
            f"[dim]Could not parse episode_number {raw!r}; defaulting to S00E00[/dim]"
        )
        return 0, 0


class BazarrMovieDetail(BaseModel):
    """A movie entry from /api/movies?radarrid=N."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    radarr_id: int = Field(alias="radarrId")
    title: str = "Unknown"
    path: str = ""
    year: int = 0


class BazarrEpisodeDetail(BaseModel):
    """An episode entry from /api/episodes?seriesid[]=N."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    sonarr_id: int = Field(alias="sonarrEpisodeId", default=0)
    season: int = 0
    episode: int = 0
    path: str = ""


T = TypeVar("T", bound=BaseModel)


class BazarrListResponse(BaseModel, Generic[T]):
    """Wrapper accepting either ``{"data": [...]}`` or bare-list responses."""

    data: list[T] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _lift_bare_list(cls, value: object) -> object:
        if isinstance(value, list):
            return {"data": value}
        return value
