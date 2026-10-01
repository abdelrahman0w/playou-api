from src.services.base import OAuthPlatform
from src.services.spotify import SpotifyConnection
from src.structs.enums import Platforms


def available_platforms() -> dict[Platforms, OAuthPlatform]:
    platforms: dict[Platforms, OAuthPlatform] = {}

    if (spotify := SpotifyConnection.get()) is not None:
        platforms[Platforms.SPOTIFY] = spotify

    return platforms
