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
from .catalog import LyricsReport  # noqa: E402
from .catalog import Track  # noqa: E402
from .catalog import TrackLyrics  # noqa: E402
from .catalog import TrackSource  # noqa: E402
from .library import Like  # noqa: E402
from .library import Playlist  # noqa: E402
from .library import PlaylistItem  # noqa: E402
from .library import PlaylistLink  # noqa: E402
from .messages import Conversation  # noqa: E402
from .messages import ConversationMember  # noqa: E402
from .messages import Message  # noqa: E402
from .messages import MessageReaction  # noqa: E402
from .messages import MessageReport  # noqa: E402
from .messages import PushSubscription  # noqa: E402
from .people import Follow  # noqa: E402
from .people import UserBlock  # noqa: E402
from .people import UserReport  # noqa: E402
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
    "Conversation",
    "ConversationMember",
    "Copy",
    "CopyItem",
    "Follow",
    "Like",
    "LinkedAccount",
    "LyricsReport",
    "Message",
    "MessageReaction",
    "MessageReport",
    "NameChange",
    "PlaybackSession",
    "Playlist",
    "PlaylistItem",
    "PlaylistLink",
    "PushSubscription",
    "Share",
    "ShareOpen",
    "SyncOperation",
    "Track",
    "TrackLyrics",
    "TrackSource",
    "User",
    "UserBlock",
    "UserReport",
]
