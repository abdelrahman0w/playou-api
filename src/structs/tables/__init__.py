import importlib
import pkgutil

from .base import Base


for module in pkgutil.walk_packages(__path__, prefix=f"{__name__}."):
    importlib.import_module(module.name)

from .accounts import LinkedAccount  # noqa: E402
from .auth import AuthEmailCode  # noqa: E402
from .auth import AuthSession  # noqa: E402
from .auth import NameChange  # noqa: E402
from .auth import User  # noqa: E402
from .catalog import Track  # noqa: E402
from .catalog import TrackSource  # noqa: E402
from .library import Like  # noqa: E402
from .library import Playlist  # noqa: E402
from .library import PlaylistItem  # noqa: E402
from .library import PlaylistLink  # noqa: E402
from .playback import PlaybackSession  # noqa: E402
from .shares import Share  # noqa: E402
from .shares import ShareOpen  # noqa: E402
from .sync import Copy  # noqa: E402
from .sync import CopyItem  # noqa: E402
from .sync import SyncOperation  # noqa: E402


__all__ = [
    "AuthEmailCode",
    "AuthSession",
    "Base",
    "Copy",
    "CopyItem",
    "Like",
    "LinkedAccount",
    "NameChange",
    "PlaybackSession",
    "Playlist",
    "PlaylistItem",
    "PlaylistLink",
    "Share",
    "ShareOpen",
    "SyncOperation",
    "Track",
    "TrackSource",
    "User",
]
