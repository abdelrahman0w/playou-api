from pydantic import BaseModel
from pydantic import Field


class SoundCloudToken(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None
    scope: str | None = None


class SoundCloudTokenError(BaseModel):
    error: str
    error_description: str | None = None


class SoundCloudMe(BaseModel):
    urn: str
    username: str | None = None
    likes_count: int | None = None


class SoundCloudUser(BaseModel):
    urn: str | None = None
    username: str | None = None


class SoundCloudTrack(BaseModel):
    urn: str
    title: str | None = None
    metadata_artist: str | None = None
    user: SoundCloudUser = Field(default_factory=SoundCloudUser)
    duration: int | None = None
    isrc: str | None = None
    artwork_url: str | None = None
    permalink_url: str | None = None


class SoundCloudTracks(BaseModel):
    collection: list[SoundCloudTrack] = Field(default_factory=list)
    next_href: str | None = None


class SoundCloudStreams(BaseModel):
    hls_aac_160_url: str | None = None
    hls_aac_96_url: str | None = None


class SoundCloudPlaylist(BaseModel):
    urn: str
    title: str | None = None
    description: str | None = None
    user: SoundCloudUser = Field(default_factory=SoundCloudUser)
    last_modified: str | None = None
    track_count: int | None = None
    artwork_url: str | None = None
    permalink_url: str | None = None


class SoundCloudPlaylists(BaseModel):
    collection: list[SoundCloudPlaylist] = Field(default_factory=list)
    next_href: str | None = None
