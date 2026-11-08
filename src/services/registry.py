from src.services.base import OAuthPlatform
from src.services.soundcloud import SoundCloudConnection
from src.services.spotify import SpotifyConnection
from src.services.youtube import YouTubeConnection
from src.structs.enums import Platforms


def available_platforms() -> dict[Platforms, OAuthPlatform]:
    platforms: dict[Platforms, OAuthPlatform] = {}

    if (spotify := SpotifyConnection.get()) is not None:
        platforms[Platforms.SPOTIFY] = spotify
    if (youtube := YouTubeConnection.get()) is not None:
        platforms[Platforms.YOUTUBE] = youtube
    if (soundcloud := SoundCloudConnection.get()) is not None:
        platforms[Platforms.SOUNDCLOUD] = soundcloud

    return platforms
