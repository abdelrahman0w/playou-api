from .base import MusicPlatform
from .base import OAuthPlatform
from .lrclib import LrclibConnection
from .lrclib import LrclibService
from .registry import available_platforms
from .resend import ResendConnection
from .resend import ResendService
from .spotify import SpotifyConnection
from .spotify import SpotifyService
from .youtube import YouTubeConnection
from .youtube import YouTubeService


__all__ = [
    "LrclibConnection",
    "LrclibService",
    "MusicPlatform",
    "OAuthPlatform",
    "ResendConnection",
    "ResendService",
    "SpotifyConnection",
    "SpotifyService",
    "YouTubeConnection",
    "YouTubeService",
    "available_platforms",
]
