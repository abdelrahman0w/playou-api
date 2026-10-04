from datetime import datetime

from pydantic import BaseModel
from pydantic import Field


class GoogleToken(BaseModel):
    access_token: str
    expires_in: int | None = None
    refresh_token: str | None = None
    refresh_token_expires_in: int | None = None
    scope: str = ""


class GoogleTokenError(BaseModel):
    error: str
    error_description: str | None = None


class GoogleUser(BaseModel):
    sub: str
    name: str | None = None


class ChannelSnippet(BaseModel):
    title: str | None = None


class RelatedPlaylists(BaseModel):
    likes: str | None = None


class ChannelContent(BaseModel):
    related_playlists: RelatedPlaylists = Field(
        default_factory=RelatedPlaylists,
        alias="relatedPlaylists",
    )


class Channel(BaseModel):
    id: str
    snippet: ChannelSnippet = Field(default_factory=ChannelSnippet)
    content_details: ChannelContent = Field(
        default_factory=ChannelContent,
        alias="contentDetails",
    )


class Channels(BaseModel):
    items: list[Channel] = Field(default_factory=list)


class SearchId(BaseModel):
    video_id: str | None = Field(default=None, alias="videoId")


class SearchItem(BaseModel):
    id: SearchId


class SearchPage(BaseModel):
    items: list[SearchItem] = Field(default_factory=list)


class Thumbnail(BaseModel):
    url: str


class VideoSnippet(BaseModel):
    title: str
    channel_title: str = Field(default="", alias="channelTitle")
    category_id: str | None = Field(default=None, alias="categoryId")
    thumbnails: dict[str, Thumbnail] = Field(default_factory=dict)


class VideoDetails(BaseModel):
    duration: str | None = None


class Video(BaseModel):
    id: str
    snippet: VideoSnippet
    content_details: VideoDetails = Field(
        default_factory=VideoDetails, alias="contentDetails"
    )


class Videos(BaseModel):
    items: list[Video] = Field(default_factory=list)


class ErrorReason(BaseModel):
    reason: str | None = None


class ErrorBody(BaseModel):
    message: str | None = None
    errors: list[ErrorReason] = Field(default_factory=list)


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class PageInfo(BaseModel):
    total_results: int = Field(default=0, alias="totalResults")


class ItemSnippet(BaseModel):
    published_at: datetime | None = Field(default=None, alias="publishedAt")


class ItemContent(BaseModel):
    video_id: str = Field(alias="videoId")


class PlaylistItem(BaseModel):
    id: str
    snippet: ItemSnippet = Field(default_factory=ItemSnippet)
    content_details: ItemContent = Field(alias="contentDetails")


class PlaylistItems(BaseModel):
    items: list[PlaylistItem] = Field(default_factory=list)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")
    page_info: PageInfo = Field(default_factory=PageInfo, alias="pageInfo")


class PlaylistSnippet(BaseModel):
    title: str
    description: str = ""
    channel_id: str | None = Field(default=None, alias="channelId")
    channel_title: str | None = Field(default=None, alias="channelTitle")
    thumbnails: dict[str, Thumbnail] = Field(default_factory=dict)


class Playlist(BaseModel):
    id: str
    etag: str | None = None
    snippet: PlaylistSnippet


class Playlists(BaseModel):
    items: list[Playlist] = Field(default_factory=list)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")
