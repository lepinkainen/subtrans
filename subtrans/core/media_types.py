"""Type system for media items (movies, episodes)."""

from typing import Union, TypeGuard

from .models import Movie, Episode

# Union type for all media types
MediaType = Union[Movie, Episode]


def is_movie(item: MediaType) -> TypeGuard[Movie]:
    """
    Type guard to check if a media item is a Movie.

    Args:
        item: Media item to check

    Returns:
        True if item is a Movie, False otherwise
    """
    return isinstance(item, Movie)


def is_episode(item: MediaType) -> TypeGuard[Episode]:
    """
    Type guard to check if a media item is an Episode.

    Args:
        item: Media item to check

    Returns:
        True if item is an Episode, False otherwise
    """
    return isinstance(item, Episode)
