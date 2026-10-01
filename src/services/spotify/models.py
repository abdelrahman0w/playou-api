from pydantic import BaseModel
from pydantic import Field


class SpotifyToken(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None
    refresh_token_expires_in: int | None = None
    scope: str = ""


class SpotifyTokenError(BaseModel):
    error: str
    error_description: str | None = None


class SpotifyErrorDetail(BaseModel):
    message: str | None = None


class SpotifyError(BaseModel):
    error: SpotifyErrorDetail


class SpotifyUser(BaseModel):
    id: str
    display_name: str | None = None


class SpotifyNamed(BaseModel):
    name: str


class SpotifyImage(BaseModel):
    url: str


class SpotifyAlbum(BaseModel):
    name: str
    images: list[SpotifyImage] = Field(default_factory=list)


class SpotifyExternalIds(BaseModel):
    isrc: str | None = None


class SpotifyExternalUrls(BaseModel):
    spotify: str | None = None


class SpotifyTrack(BaseModel):
    id: str
    name: str
    artists: list[SpotifyNamed] = Field(default_factory=list)
    album: SpotifyAlbum | None = None
    duration_ms: int | None = None
    explicit: bool | None = None
    external_ids: SpotifyExternalIds = Field(default_factory=SpotifyExternalIds)
    external_urls: SpotifyExternalUrls = Field(default_factory=SpotifyExternalUrls)


class SpotifyTrackPage(BaseModel):
    items: list[SpotifyTrack | None] = Field(default_factory=list)


class SpotifySearch(BaseModel):
    tracks: SpotifyTrackPage = Field(default_factory=SpotifyTrackPage)
