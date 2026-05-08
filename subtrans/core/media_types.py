"""Type system for media items (movies, episodes)."""

from typing import TypeGuard, Union

from .models import Episode, MediaItem, Movie

# Closed union of concrete media types. Use this when callers must dispatch on
# the runtime variant; prefer the structural ``MediaItem`` protocol elsewhere.
MediaType = Union[Movie, Episode]


def is_movie(item: MediaItem | object) -> TypeGuard[Movie]:
    """True if ``item`` is a concrete `Movie` instance."""
    return isinstance(item, Movie)


def is_episode(item: MediaItem | object) -> TypeGuard[Episode]:
    """True if ``item`` is a concrete `Episode` instance."""
    return isinstance(item, Episode)
