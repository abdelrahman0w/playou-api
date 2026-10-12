# Playou API

[![python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](https://python.org/)
[![fastapi](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![postgresql](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![redis](https://img.shields.io/badge/Redis-FF4438?logo=redis&logoColor=white)](https://redis.io/)
[![uv](https://img.shields.io/badge/uv-DE5FE9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![ruff](https://img.shields.io/badge/Ruff-D7FF64?logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![mypy](https://img.shields.io/badge/mypy-2A6DB2?logo=python&logoColor=white)](https://mypy-lang.org/)
[![pre-commit](https://img.shields.io/badge/pre--commit-FAB040?logo=pre-commit&logoColor=black)](https://pre-commit.com/)

- [Playou API](#playou-api)
  - [Description](#description)
  - [Architecture](#architecture)
    - [Project Structure](#project-structure)
    - [Layers](#layers)
    - [Rules](#rules)
    - [Platforms](#platforms)
  - [Request Lifecycle](#request-lifecycle)
    - [Linking An Account](#linking-an-account)
    - [Tokens](#tokens)
    - [Search](#search)
    - [Library](#library)
    - [Imports](#imports)
    - [Playback](#playback)
  - [Usage](#usage)
    - [Clients](#clients)
    - [Available Endpoints](#available-endpoints)
    - [Errors](#errors)
    - [Rate Limiting](#rate-limiting)
    - [Jobs](#jobs)
    - [Configuration](#configuration)
    - [Logging](#logging)
  - [Setup](#setup)
    - [Using Docker](#using-docker)
    - [Manually](#manually)
    - [Spotify](#spotify)
    - [YouTube](#youtube)
  - [Testing](#testing)

## Description

**playou-api** is a [Python](https://www.python.org/) API for Playou,
one player and library over the user's music platforms.

Users link their platforms' accounts, and search, like, and keep playlists in one place,
while each track is played by its own platform. The decisions behind it are in [the plan](docs/plan.md).

> Spotify is the first platform, Apple Music, YouTube, and Anghami come next

## Architecture

The project is split into layers, each with a single responsibility,
and every layer is grouped by domain, `auth`, `accounts`, `catalog`,
so a new domain is a new folder in each layer rather than changes all over the place.

### Project Structure

```
playou-api/
├── bin/
│   ├── entrypoint.sh               the api entrypoint (--dev for reload)
│   ├── healthcheck.py              the image's health check, the api's /health/live or the worker's heartbeat
│   ├── jobs.sh                     runs a single job by name, or every job on its cron with schedule
│   └── openapi.sh                  writes the api's schema, for the web client's types
├── docs/
│   └── plan.md                     what was agreed, and what comes next
├── migrations/                     alembic migrations
├── openapi.json                    the api's schema, written by bin/openapi.sh
├── src/
│   ├── main.py                     app, lifespan, middlewares, exception handlers, routers
│   ├── settings.py                 settings read from the environment
│   ├── dependencies.py             db session, redis, the platforms, the clock, the client ip, the user
│   ├── routes/                     path, params, status
│   ├── controllers/                use cases, called by routes only
│   ├── actions/                    reusable units, called by controllers, jobs, and events
│   │   ├── accounts/               linking, token refresh, token sealing
│   │   ├── auth/                   email codes, sessions
│   │   └── catalog/                search across the platforms
│   ├── repositories/               queries only
│   ├── jobs/
│   │   ├── base.py                 what a job is, its run, help, flags, and monitor
│   │   ├── main.py                 runs a job once, by name, the sync worker, or every job on its cron
│   │   └── worker.py               the sync worker, nudged through redis, sweeping what is due
│   ├── services/                   external systems
│   │   ├── base.py                 what every music platform does, and its capabilities
│   │   ├── registry.py             the platforms that are configured
│   │   ├── spotify/
│   │   └── resend/
│   ├── providers/                  stateful infra, opened in the lifespan
│   ├── middlewares/
│   │   ├── logs_contextualizer.py  the request's context on every log line, and its log
│   │   └── rate_limit.py           the sliding window, per user or client ip
│   ├── utils/                      pure helpers, pkce and encryption among them
│   ├── structs/
│   │   ├── enums/
│   │   ├── models/                 pydantic models
│   │   │   ├── platforms.py        what the platforms and the layers share
│   │   │   ├── requests/           what comes in
│   │   │   └── responses/          what goes out
│   │   └── tables/                 sqlalchemy tables
│   └── exceptions/
└── tests/                          laid out like src, by layer
```

### Layers

| Layer | Responsibility | Called By | May Use |
| --- | --- | --- | --- |
| `routes` | The http shape of an endpoint | FastAPI | `controllers`, `dependencies`, `structs/models` |
| `controllers` | One use case per file | `routes` | `actions`, `repositories`, `services`, `providers`, `utils` |
| `actions` | Reusable logic and side effects | `controllers`, `jobs`, events | `repositories`, `services`, `providers`, `utils` |
| `repositories` | Queries, nothing else | `controllers`, `actions` | `structs/tables` |
| `services` | Talking to external systems | `controllers`, `actions` | their http clients |
| `providers` | Connections and their lifecycle | the lifespan, `dependencies`, `jobs` | `settings` |
| `utils` | Pure helpers | any layer | nothing from `src` |

### Rules

- **Tables never leave the repositories.** `structs/tables` is only imported by `repositories`
    and `migrations`, everything above them works with `structs/models`.
- **A platform's payloads stay in its service.** Each service parses its platform's responses
    into its own models, and maps them to `structs/models`, so a change in a platform's api
    is a change in its service only.
- **Capabilities, never names.** The layers above the services check what a platform can do,
    through its `Capabilities`, never which platform it is.
- **FastAPI stays at the edge.** Only `main.py`, `routes`, `dependencies.py`, `middlewares`,
    and `exception_handlers.py` import it. Everything else raises exceptions from `custom_exceptions.py`,
    and they are mapped to http errors once.
- **Repositories never commit.** The session is always passed in,
    and whoever opens it, a controller or an action, owns the transaction.
- **Tokens are stored sealed.** The platforms' tokens are encrypted before they reach a repository,
    and only `actions/accounts` seals and unseals them.
- **Jobs and events call actions, never controllers.**
- **Utils are pure.** No i/o, no state, and no imports from `src`.

### Platforms

Every platform's client implements `OAuthPlatform`, from `services/base.py`,
and declares its `Capabilities`, what it can search, like, and change:

| Platform | Linking | Search | Like | Playlists | Status |
| --- | --- | --- | --- | --- | --- |
| Spotify | OAuth with PKCE, no client secret | Yes | Yes | Yes | Linking, search, syncing the library both ways, and playback |

> Spotify answers a search with 10 results at most, it refuses a bigger `limit`, so it is capped by `SPOTIFY_SEARCH_MAX_LIMIT`

A platform without its keys, like Spotify without `SPOTIFY_CLIENT_ID`, is left out of `services/registry.py`,
so it is not offered, and asking for it is `UNSUPPORTED`.

## Request Lifecycle

### Linking An Account

```
web → GET /accounts/spotify/connect   → redis      (state → user, verifier, 10 minutes)
    ← 307 to spotify, with the state and the verifier's challenge
spotify → GET /accounts/spotify/callback?code&state
                                       → redis      (state taken, once)
                                       → spotify    (code + verifier → tokens, then the profile)
                                       → postgres   (tokens sealed, the account upserted)
        ← 303 to APP_WEB_URL/accounts?linked=spotify
```

1. The signed in user is sent to Spotify, with a random `state`, and the challenge of a PKCE verifier,
    the verifier and the user are kept in redis under the state, for `ACCOUNTS_LINK_MINUTES`
1. Spotify sends the browser back with a code and the state
1. The state is taken from redis, so it works once, and it has to be the signed in user's, for the same platform,
    so a link started by someone else is refused
1. The code is exchanged with the verifier, the tokens are sealed, and the account is stored, one per user and platform,
    linking again replaces it, which is how an account is reconnected
1. The browser is sent back to the web app, with `linked=spotify`, or with `error=<type>`

> The callback is a browser redirect, so it never answers with json, every failure goes back to the web app as `error`

### Tokens

`actions/accounts/tokens.py` hands out an account's access token, refreshing it first
when it expires within `ACCOUNTS_REFRESH_MARGIN_SECONDS`.

- The account's row is locked while it is refreshed, so concurrent requests refresh once,
    the others wait, then find it fresh. A platform that rotates refresh tokens would refuse a second refresh,
    Spotify keeps the same one, there it only saves a call
- A refused refresh sets the account's `reconnect_required_at`, it is not tried again until it is linked again
- A call Spotify answers `401`, a token it no longer takes, refreshes the token once and is tried again, `with_token`,
    so an access removed on Spotify's side is caught on the first call, not once the token expires,
    and the `warn_disconnected_accounts` job emails the owner, once, to reconnect.
    The browser's player does the same through `POST /playback/{platform}/token`, sending the token it was refused
- Tokens are sealed with `ENCRYPTION_KEYS`, a token sealed with a key that is gone needs reconnecting too

Refresh tokens expire too, so every account keeps when its refresh token expires,
as the platform says it when it does, `refresh_token_expires_in`, or from its lifetime, `SPOTIFY_REFRESH_TOKEN_DAYS`.

Spotify's lasts 6 months from the link, and
["refreshing an access token does not extend the refresh token's lifetime"](https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens),
it usually answers no new refresh token at all, and the stored one goes on, so nothing keeps a Spotify account past its 6 months,
its user links it again.

- A refresh only moves the expiry on when the platform says the new one, or when its refresh starts the lifetime over,
    `refresh_extends_lifetime`, which Spotify's does not
- An account's status is never stored, it is `NEEDS_RECONNECT` once `reconnect_required_at` is set,
    or its refresh token's expiry has passed, the moment it passes, so the web app and the search know before a request fails
- The [`check_expiring_accounts`](#jobs) job refreshes the ones expiring within `ACCOUNTS_KEEP_ALIVE_DAYS`,
    on the platforms whose refresh extends it
- It emails the users whose account expires within `ACCOUNTS_EXPIRY_WARNING_DAYS` to reconnect it,
    once an expiry, in their language, linking to `APP_WEB_URL/accounts?reconnect=<platform>`,
    a hundred a call through Resend's batch, under an idempotency key, so a run that fails after sending never sends twice,
    a new expiry, linking again or a refresh that moves it on, is warned about again
- `GET /accounts` answers `refresh_expires_at`, so the web app can ask for a reconnect before it is too late

> Reconnecting is linking again, if the user is still signed in to Spotify, and already approved the scopes,
> Spotify sends them straight back without asking, so it takes a click

> Without `RESEND_API_KEY`, no warning is sent, and none is marked sent, so they go out once there is one,
> a warning that fails is tried again the next run
### Search

1. The user's linked accounts are read
1. Every account's platform is searched at once, each within `SEARCH_PLATFORM_TIMEOUT_SECONDS`
1. Each platform's results are cached for `SEARCH_CACHE_SECONDS`, per account and query
1. A platform that fails, times out, or needs reconnecting is reported with its status, never failing the rest
1. YouTube is searched on demand, only when the others found nothing, or with `everywhere=true`, otherwise it is `SKIPPED`,
    since a search is 100 of its 10,000 units a day for the whole app, it is searched with the api key, so its results
    are no one's, cached for `SEARCH_SHARED_CACHE_SECONDS` for everyone, and a spent day is `QUOTA_EXHAUSTED`,
    `YOUTUBE_SEARCH_ON_DEMAND=false` searches it with the others, once the quota allows
1. A `SKIPPED` platform still answers the songs the catalog has on it, every song any user imported or found,
    searched like the library, every word matching, the closest first, without a unit spent, the videos YouTube refused left out
1. A result is stored in the catalog, by its isrc, or for youtube, which has none, joined to the song with the same
    title and artist within 3 seconds of its length, so a song on Spotify and YouTube is one, with both its sources,
    and a source without an isrc never rewrites the details of a song that has one
    - The songs it could be are the 50 closest titles within those 3 seconds, its title cleaned of `feat.` and `(Official Video)`,
        found in postgres by a GiST index on `tracks (duration_ms, sort_title)`, and `same_song` decides,
        so a crowded catalog costs no more, and a miss only ever stores the song twice, never joins the wrong one
    - A song already stored is only written when something about it changed, so a search answered from the cache writes nothing
1. The platforms are searched at once, and their results stored one after the other, in one transaction,
    the ones with an isrc first, so a song two platforms found in the same search is one
1. `CATALOG_MATCH_ACROSS_SCRIPTS=true` also joins a song written in Arabic on one platform and in Latin letters on the other,
    `إزاي` and `Ezay`, `رن رن` and `Ren Ren`, by how its title and artists sound, `sounds` in `src/utils/matching.py`,
    the vowels dropped, the letters that sound alike as one, `3` and `7` read as Arabizi, either half of `Title - العنوان` compared.
    Only across the two scripts, never within one, and still within 3 seconds of its length, it is off by default,
    and it joins what is stored from then on, not the songs stored apart before it
1. `POST /catalog/tracks/{id}/find/{platform}` looks a song up on one more app, its title and first artist, 5 results,
    stored like any search, so the one that is the same song is joined to it, and answers the song, with the new source or without,
    on YouTube it is one search, 100 units, a song already there costs nothing

### Library

The library is the app's, likes and playlists live here, and are pushed to the platforms the user turned it on for.

- Search stores what it finds in the catalog, a track once, merged across platforms by its ISRC,
    so every result has an `id` to like it or add it to a playlist by
- Nothing is deleted, an unliked track, a removed playlist, or a track removed from one is kept,
    with `removed_at` and `removed_by`, `USER` or `PLATFORM`, so the library mirrors the platforms,
    the lists leave them out, unless `include_removed=true`, and liking or adding it again brings it back
- A change and its push are stored in one transaction, a row in `sync_operations`, the outbox
- `q` searches the likes by title, artists, and album, and the playlists by name, every word has to match,
    whatever the case, the accents, the Arabic marks, or the form of alef, `أ` `إ` `آ` are `ا`, `ة` is `ه`, `ى` is `ي`,
    through `search_fold` and `track_search_text`, Postgres functions on `unaccent`, the tracks' indexed by `pg_trgm`
- `tracks.sort_title` and `sort_artist` are `search_fold` of the title and the first artist, stored, sorted by, and matched on,
    postgres never computes them again when the function changes, so a migration that changes `search_fold`
    recomputes them too, `update tracks set title = title`, in batches, or sorting and matching drift from it

```
PUT /library/likes/{id} → postgres   (the like, and its operation, one transaction)
                        ← 200
          after the response → the sync worker → spotify   (or the api itself without a worker, the sweep retries what fails)
```

- An operation holds what to match, not the change, a like or a playlist,
    the push reads the library when it runs, so changes in a row become one push,
    a like then an unlike push the unlike only, and a retry is never a step behind
- A playlist's push makes it on the platform first, then renames it, and adds what is missing,
    it only removes there what was removed here, never what was added in the platform's app
- A playlist made on the platform is remembered right away, on its own, so a push that fails after it never makes a second copy
- A playlist deleted in the platform's app is removed here too, by `PLATFORM`
- A failed push waits `SYNC_RETRY_SECONDS`, doubled each attempt up to `SYNC_LONGEST_RETRY_SECONDS`,
    and gives up after `SYNC_MAX_ATTEMPTS`, an account that has to be linked again waits without using an attempt
- Operations are claimed with `FOR UPDATE SKIP LOCKED` and leased, `leased_until`, then the platform is called with no transaction open,
    the lease renewed every third of `SYNC_LEASE_SECONDS` while it answers, so two workers never push the same one,
    and one that crashed is pushed again once its lease is up, or right away when it was stopped
- A change made while its push runs bumps the operation's `requests`, so the push leaves it pending, and it is pushed again right after
- A user's due likes are pushed together, 40 a call, a playlist's tracks 100 a call
- The catalog stores tracks in bulk, a few queries for a batch of 500, whatever its size
- An operation's `status` is a column postgres computes, `PENDING` until `finished_at` is set, then its `outcome`, `DONE`, `SKIPPED`, or `FAILED`, it is never written, so it never disagrees with them
- An account's status is not a column, it depends on the time, and a computed column cannot, it is `status_at(now)`, from `reconnect_required_at` and the refresh token's expiry
- `PATCH /accounts/{platform}/preferences` turns pushing likes or playlists to a platform off, or on

### Imports

The platforms' libraries come in too, the user's liked songs, their own and collaborative playlists with their tracks,
and the ones they follow, without their tracks, which Spotify does not give, as `FOLLOWED`, read only, with their owner, cover, and link.

- An import is a row in the same queue, `IMPORT`, asked for when an account is linked, when the library is opened
    and the last import is older than `IMPORT_STALE_MINUTES`, checked once every `IMPORT_CHECK_SECONDS` a user,
    by `POST /library/import`, and by the worker's sweep for the accounts not imported for `IMPORT_EVERY_MINUTES`,
    `IMPORT_SCHEDULE_BATCH_SIZE` a sweep, skipping the ones with an import pending, or one that failed within `IMPORT_EVERY_MINUTES`
- `POST /library/import` within `IMPORT_COOLDOWN_SECONDS` of the last import starts nothing, it answers the status,
    so tapping sync again and again cannot flood spotify, an import already queued or running is joined, never doubled
- Linking and `POST /library/import` import right after the response, through the sync worker, without waiting for the sweep,
    which still takes the scheduled ones, and the ones a crash left
- A full read reports how far it got, `progress` in `GET /library/sync`, the liked songs read, then the playlists,
    a refresh, which stops at the first known like, reports none
- A playlist is linked once per user, two users following the same one each have their own
- The sweep runs up to `IMPORT_BATCH_SIZE`, one at a time, each leased for `IMPORT_LEASE_MINUTES` when it starts, and renewed every third of it while it runs, so one account is imported once at a time,
    an import whose lease ran out without it settling stopped the worker, it counts as a failed attempt, and gives up after `SYNC_MAX_ATTEMPTS`,
    a run that crashes is taken again once its lease is up, and asking again while it runs joins it
- Liked songs are read newest first, up to the first one already liked, and Spotify's count is compared with the last import's,
    `likes_total`, a count that does not add up reads them all, and so does the first import of the day, `IMPORT_FULL_EVERY_HOURS`,
    a song unliked there is `removed_by` `PLATFORM` here, only once none of its recordings' ids is still liked
- An owned playlist's tracks are read only when its `snapshot_id` changed, and follow Spotify's, in its order,
    a playlist gone from Spotify is `removed_by` `PLATFORM`
- A like or a playlist waiting to be pushed wins, the import leaves it, and an import never asks for a push
- YouTube's liked music is its liked videos in the music category, the others are counted, never liked here,
    its playlists are the user's own, YouTube lists no followed ones, a playlist is read again when its `etag` changed,
    an import is about 2 units for 50 songs
- Pushing to YouTube is off until turned on, a like or a playlist change costs 50 units, so each account has
    `YOUTUBE_DAILY_PUSH_UNITS` a day, over it, or over the app's, a push waits for midnight Pacific time without an attempt,
    finding songs to copy there has its own share, `YOUTUBE_DAILY_FIND_UNITS`, and copies only playlists unless `YOUTUBE_COPY_LIKES` is on,
    and only a song YouTube already has here is pushed, a song only on Spotify is skipped, never searched for
- A like or a playlist keeps where it was imported from, `imported_from`, null when made here, so what an unlinked platform
    left can be removed, `DELETE /library/data/{platform}`, sparing the likes still playable on a linked platform
- Deleting only ever deletes here, nothing is sent to the platforms, and `DATA_DELETION_ENABLED=false` refuses it,
    `403`, the user's `can_delete_data` says so, an erasure request is then `bin/jobs.sh delete_user_data <email> --account`
- `GET /library/sync` answers each account's import, `IDLE`, `SYNCING`, or `FAILED`, and when it was last imported

### Playback

The API never streams audio, each platform plays its own, the API tells it what, and on which device.
Only Spotify plays through these, YouTube Music plays in the browser's own YouTube player, which needs nothing from the API but the songs' video ids,
the token, devices, and play endpoints answer it `UNSUPPORTED`.

- `GET /playback/{platform}/token` answers the account's access token, refreshed if it has to be, never cached,
    for the Web Playback SDK, which makes the browser a Spotify Connect device
- `GET /playback/{platform}/devices` answers the user's devices, the browser's, their phone's, their desktop app's
- `POST /playback/{platform}/play` plays on one, the tracks given, by their ids here, or a playlist, from the `offset`th track
    - A playlist on the platform is played as itself, so a followed one plays too, though its tracks are never read
    - A playlist not pushed yet is played by its tracks, those the platform has
- `POST /playback/youtube/blocked` remembers a video YouTube refused to play in PlaYou, `track_sources.embed_blocked_at`,
    so its source is sent back `embed_blocked` and the web plays the song from another app, or not at all
- Spotify plays for Premium only, and `GET /me` no longer says who has it, so a refusal is `PLATFORM_PREMIUM_REQUIRED`,
    and no open device is `NO_ACTIVE_DEVICE`
- Playing needs the `streaming`, `user-read-playback-state`, and `user-modify-playback-state` scopes,
    an account linked without them answers `PLATFORM_SCOPES_MISSING`, and lists them in `missing_scopes`, linking it again grants them
- Pausing, seeking, skipping, and the queue are the client's, through the SDK, so a queue can span platforms
- The playback session, `playback_sessions`, one a user, is what plays, the list and its cursor, up next, the song,
    and where it got to, `position_ms` at `position_at`, and on which device, so any client carries on from it
    - Only the device playing saves it, each save sends the `version` it last saw and moves it on by one,
        in one statement, so a device left behind is refused with `PLAYBACK_SESSION_CHANGED`, and reads it again
    - Claiming it moves it to another device, paused, at the position it got to, the device left behind sees that on its next read
    - It holds track ids, up to 100 in the list and 100 up next, and answers with their songs, the ones still in the catalog
    - It goes with the user's data, and `prune_auth` drops the ones untouched for `PLAYBACK_SESSION_DAYS`, 30
    - `GET /playback/session` answers an `ETag`, the user, the version, when the session was last written, and the newest change
        to its songs and their sources hashed, so a session started again, or a song given a new source, is sent again,
        with `Cache-Control: private, no-cache`,
        and `304` with no body while it has not changed, the web fetches it with `cache: 'no-cache'`, so its browser asks
        with `If-None-Match`, and an unchanged poll loads no songs

## Usage

### Clients

Every client opens on the same rule, a signed in user starts on Home, and only a signed out one sees the landing, or the sign in.
There is no separate home route, `/` is Home or the landing, whichever fits.

- The web asks `GET /auth/me`, with a hint kept in the browser so a signed in visitor never sees the landing page flash,
    see [playou-web](../playou-web#authentication)
- A native client keeps its own session, the bearer token from `POST /auth/email/verify`, and opens on Home while it has one,
    a `401` signs it out

### Available Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health/live` | Liveness |
| `GET` | `/health/ready` | Readiness, postgres and redis |
| `POST` | `/auth/email/code` | Emails a sign in code |
| `POST` | `/auth/email/verify` | Signs in with the code, and sets the session cookie, or answers the token with `"transport": "bearer"` |
| `POST` | `/auth/sign-out` | Ends the session |
| `GET` | `/auth/me` | The signed in user, and whether they may delete their data, `can_delete_data` |
| `DELETE` | `/auth/me` | Deletes the account and everything of it, and signs out |
| `GET` | `/accounts` | The linked accounts, with what each platform can do, `expires_soon`, within `ACCOUNTS_EXPIRY_WARNING_DAYS`, and `missing_scopes` |
| `GET` | `/accounts/{platform}/connect` | Starts linking, redirects to the platform |
| `GET` | `/accounts/{platform}/callback` | Where the platform sends the browser back, redirects to the web app |
| `DELETE` | `/accounts/{platform}` | Unlinks the account, with `remove_data=true` also what was imported from it |
| `GET` | `/catalog/search?q=&limit=&everywhere=` | Searches every linked platform, `limit` up to 50, 20 by default |
| `POST` | `/catalog/tracks/{track_id}/find/{platform}` | Looks a song up on another linked app, and joins what is the same song |
| `GET` | `/accounts/{platform}/preferences` | What the library pushes to the platform |
| `PATCH` | `/accounts/{platform}/preferences` | Turns pushing likes or playlists on or off, `{"push_likes": false}` |
| `GET` | `/library/likes?page=&page_size=&include_removed=&platform=&q=` | The liked tracks, newest first, `q` searches them |
| `PUT` | `/library/likes/{track_id}` | Likes a track |
| `DELETE` | `/library/likes/{track_id}` | Unlikes it, the like is kept as removed |
| `GET` | `/library/playlists?page=&page_size=&include_removed=&kind=&platform=&q=&sort=` | The playlists, pinned first, then newest, by `NAME`, or in the user's own order with `CUSTOM`, `OWNED` or `FOLLOWED`, `q` searches their names |
| `GET` | `/library/sync` | Each linked account's import, `IDLE`, `SYNCING`, or `FAILED` |
| `GET` | `/library/data` | What the unlinked platforms left, their imported likes and playlists |
| `DELETE` | `/library/data/{platform}` | Removes what an unlinked platform left |
| `DELETE` | `/library/data` | Clears the library, and unlinks every platform unless `unlink=false`, the account stays |
| `POST` | `/library/import` | Asks for an import of every linked account now |
| `GET` | `/playback/{platform}/token` | The access token for the platform's web player, never cached |
| `GET` | `/playback/{platform}/devices` | The user's devices on the platform |
| `POST` | `/playback/{platform}/play` | Plays `{"track_ids": [...]}` or `{"playlist_id": ...}`, with `device_id`, `offset`, and `position_ms` |
| `GET` | `/playback/session` | What plays, where, and where it got to, with its songs, `null` when nothing |
| `PUT` | `/playback/session` | Saves it from the device playing, with the `version` it last saw, a newer one answers `PLAYBACK_SESSION_CHANGED` |
| `POST` | `/playback/session/claim` | Continues it on this device, `{"device_id", "device_name"}`, at the position it got to |
| `DELETE` | `/playback/session` | Forgets it |
| `POST` | `/playback/youtube/blocked` | Marks `{"platform_id": ...}` as a video YouTube won't play outside its site |
| `POST` | `/library/playlists` | Makes one, `{"name": "Road", "description": "Trip"}` |
| `GET` | `/library/playlists/{id}?include_removed=` | A playlist, with its tracks in order |
| `PATCH` | `/library/playlists/{id}` | Renames it, or changes its description, a followed one is `UNSUPPORTED` |
| `DELETE` | `/library/playlists/{id}` | Removes it, it is kept as removed |
| `PUT` | `/library/playlists/{id}/pin` | Pins it, pinned playlists come first in every sort, `DELETE` unpins it |
| `PUT` | `/library/playlists/order` | The user's own order, `{"playlist_ids": [...]}`, the ones left out come first, newest first |
| `POST` | `/library/playlists/{id}/items` | Appends tracks, `{"track_ids": [...]}`, up to 100, a track there stays put |
| `DELETE` | `/library/playlists/{id}/items/{track_id}` | Removes a track from it |

Everything but the health probes and signing in needs a session.
The web sends it as the HttpOnly `playou_session` cookie, apps send the same token as `Authorization: Bearer <token>`,
and the cookie comes first when both are there.

An app asks for its token when it verifies the code, and keeps it in the keychain or keystore:

```json
POST /auth/email/verify
{"email": "someone@example.com", "code": "123456", "transport": "bearer"}

{"user": {"id": "...", "email": "someone@example.com", ...}, "token": "...", "expires_in_seconds": 2592000}
```

> The session is extended while it is used, so `expires_in_seconds` counts from the last use, no cookie is set for a bearer session

A search answers each platform's results, and its status, `OK`, `FAILED`, `TIMED_OUT`, `RATE_LIMITED`, or `NEEDS_RECONNECT`:

```json
{
    "query": "never gonna",
    "platforms": [
        {
            "platform": "spotify",
            "status": "OK",
            "tracks": [
                {
                    "platform": "spotify",
                    "platform_id": "4uLU6hMCjMI75M1A2tKUQC",
                    "title": "Never Gonna Give You Up",
                    "artists": ["Rick Astley"],
                    "album": "Whenever You Need Somebody",
                    "duration_ms": 213573,
                    "isrc": "GBARL9300135",
                    "explicit": false,
                    "artwork_url": "https://i.scdn.co/image/...",
                    "url": "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"
                }
            ]
        }
    ]
}
```

### Errors

Errors share a single shape:

```json
{
    "error": {
        "type": "PLATFORM_NOT_LINKED",
        "message": "Spotify is not linked"
    }
}
```

| Status | Type | When |
| --- | --- | --- |
| `400` | `INVALID_CODE` | The code is wrong, expired, or used |
| `400` | `INVALID_OAUTH_STATE` | A link's state is missing, expired, used, or another user's |
| `400` | `UNSUPPORTED` | The platform is not available, or cannot do that |
| `401` | `UNAUTHORIZED` | The endpoint needs a session, and there is none |
| `403` | `FORBIDDEN` | The request comes from a site that may not make it |
| `404` | `NOT_FOUND` | The requested item does not exist |
| `409` | `PLATFORM_NOT_LINKED` | The user has not linked that platform |
| `409` | `PLATFORM_RECONNECT_REQUIRED` | The platform no longer accepts the account, it has to be linked again |
| `409` | `PLATFORM_SCOPES_MISSING` | The account was linked without what playing needs, it has to be linked again |
| `409` | `NO_ACTIVE_DEVICE` | The platform has no device to play on |
| `409` | `PLAYBACK_SESSION_CHANGED` | Another device saved the playback session since this one read it |
| `403` | `PLATFORM_PREMIUM_REQUIRED` | The platform only plays for its paying users |
| `429` | `RATE_LIMITED` | Too many requests, see [rate limiting](#rate-limiting) |
| `502` | `PLATFORM_ERROR` | The platform responded with an error or with something unusable |
| `503` | `PLATFORM_UNAVAILABLE` | The platform could not be reached |
| `503` | `PLATFORM_RATE_LIMITED` | The platform is limiting the app's requests, with `Retry-After` |
| `503` | `QUOTA_EXHAUSTED` | YouTube's units for the day are spent, back after midnight Pacific time |
| `503` | `EMAIL_UNAVAILABLE` | The code could not be sent |
| `504` | `PLATFORM_TIMEOUT` | The platform did not respond in time |
| `500` | `INTERNAL` | Anything unexpected, reported to error tracking |

> Invalid parameters return FastAPI's default `422` validation response

### Rate Limiting

Every request is limited per signed in user, and per client ip without a session, 120 requests a minute by default,
over a sliding window in redis, shared by every replica.

The client ip is read from cloudflare's `CF-Connecting-IP` header, and from the peer address without it.
IPv6 clients are counted by their `/64`.

> The header is trusted as is, which is only safe while the origin is reachable through cloudflare alone

> The health probes are never limited, and requests go through when redis is down,
> or does not answer within `RATE_LIMIT_TIMEOUT_SECONDS`

A platform limits the app's requests too, every user's together, so a `429` from it pauses that platform for everyone,
for as long as its `Retry-After` says, or `SPOTIFY_RATE_LIMIT_SECONDS` without it, through a key in redis every replica and job shares.

- While it is paused, nothing is sent to it, a call fails right away as `PLATFORM_RATE_LIMITED`
- A search answers the platform as `RATE_LIMITED`, the others still answer
- A push waits for the pause to end, without using an attempt
- A longer pause is never cut short by a shorter one, and without redis nothing is paused

### Jobs

Jobs are run once by name through `bin/jobs.sh`, `bin/jobs.sh <job> --help` lists their flags:

| Job | Cron | Description |
| --- | --- | --- |
| `push_library_changes` | the worker | Pushes the library's changes that are due, the ones the push after a request did not finish, `SYNC_PUSH_BATCH_SIZE` a run |
| `import_libraries` | the worker | Asks for the imports that are due, and imports the asked for, `IMPORT_BATCH_SIZE` a run, see [imports](#imports) |
| `copy_libraries` | the worker | Finds the songs being copied to another app, `CATALOG_COPY_BATCH_SIZE` a copy a run, then sends the likes and playlists there |
| `prune_sync_operations` | `0 1 * * *` | Drops the sync operations finished more than `SYNC_RETENTION_DAYS` ago |
| `check_expiring_accounts` | `0 3 * * *` | Emails the users of the accounts expiring within `ACCOUNTS_EXPIRY_WARNING_DAYS` to reconnect, once, then refreshes the ones expiring within `ACCOUNTS_KEEP_ALIVE_DAYS`, on the platforms whose refresh extends the lifetime, the soonest first, `ACCOUNTS_KEEP_ALIVE_BATCH_SIZE` a run, one at a time. A refused refresh sets `reconnect_required_at`, a failed one is tried again the next run |
| `warn_disconnected_accounts` | `*/5 * * * *` | Emails the users whose platform refused their account, once, until it is linked again |
| `forget_disconnected_accounts` | `15 3 * * *` | Unlinks the accounts refused for `ACCOUNTS_FORGET_DISCONNECTED_DAYS`, 7, unless `ACCOUNTS_FORGET_DISCONNECTED` is false, and removes the likes and playlists that came only from them, as YouTube's API policy asks once access is revoked |
| `prune_auth` | `30 0 * * *` | Drops the expired sessions, the codes used or expired, and the playback sessions untouched for `PLAYBACK_SESSION_DAYS` |
| `merge_tracks` | by hand | Merges the tracks saved twice for one song and uppercases the isrcs, `--dry-run` only logs them |
| `delete_user_data` | by hand | Clears a user's library and linked apps by their email, `--account` deletes the account too, whatever `DATA_DELETION_ENABLED` says |

In production, each job is a schedule in dokploy, in the api's application, under **Schedules**,
with the `sh` shell, running `/app/bin/jobs.sh <job>` in the api's container, with its environment:

| Name | Cron | Command | Enabled |
| --- | --- | --- | --- |
| `prune_sync_operations` | `0 1 * * *` | `/app/bin/jobs.sh prune_sync_operations` | Yes |
| `check_expiring_accounts` | `0 3 * * *` | `/app/bin/jobs.sh check_expiring_accounts` | Yes |
| `warn_disconnected_accounts` | `*/5 * * * *` | `/app/bin/jobs.sh warn_disconnected_accounts` | Yes |
| `forget_disconnected_accounts` | `15 3 * * *` | `/app/bin/jobs.sh forget_disconnected_accounts` | Yes |
| `prune_auth` | `30 0 * * *` | `/app/bin/jobs.sh prune_auth` | Yes |

> Any hour does for them, they follow the server's clock, and a day missed is made up the next one,
> the keep alive starts `ACCOUNTS_KEEP_ALIVE_DAYS` before an expiry, and an account past it is marked by the next run

> The sync jobs, `push_library_changes`, `import_libraries`, and `prune_sync_operations`, come with the library, see [the plan](docs/plan.md#sync)

#### The sync worker

Pushing, importing and copying run in their own application in dokploy, `playou-worker`, from the api's image,
running `/app/bin/jobs.sh worker`, with the api's environment, and `DATABASE_POOL_SIZE` of its own, 5 is plenty.
It runs no migrations, the api does.

After a like, an edit, a copy or an import asked for, the api hands the user's work to the worker on the `sync:nudges` list in redis,
and it starts within milliseconds, pushes `WORKER_PUSH_CONCURRENCY` users at a time, imports and copies `WORKER_CONCURRENCY`,
in slots of their own, so a long import never holds a like back, and a user's work asked for again while it runs is run once more after.
Every `WORKER_SWEEP_SECONDS`, 15, it also sweeps what is due, the same as `push_library_changes`, `import_libraries` and `copy_libraries`,
retries, scheduled imports and paused copies, each in a loop of its own, so a long import never holds a retry or a copy back.
A copy saves each song as soon as it is found, so a worker stopped midway loses none of the searches it finished.

It keeps `sync:worker:alive` in redis, every `WORKER_HEARTBEAT_SECONDS`, and drops it when stopped,
only while it is listening for nudges, so a worker that cannot hear them hands the work back.
While the key is missing, or redis is down, the api does the work itself after the response, as it did before the worker,
so the worker going down slows nothing for the users. Several workers can run, a push is leased, an import too, and a copy is locked.

> The api only does what a request asks for, the sweeps are the worker's alone, so while it is down, and the schedules are off,
> nothing retries a failed push, runs a scheduled import, or resumes a paused copy, when it is down for more than a few minutes,
> turn the `push_library_changes`, `import_libraries` and `copy_libraries` schedules back on until it is back

Its health is the image's `HEALTHCHECK`, `bin/healthcheck.py`, healthy while `/health/live` answers, the api,
or the heartbeat file, `WORKER_HEALTH_FILE`, is newer than 30 seconds, the worker, so leave the health check empty in dokploy,
it sends one written there as a single string, which docker cannot run, and every task then stays `Starting`.
The swarm settings for the api, the worker, and the web are in [perf-updates.md](perf-updates.md#23-dokploy-swarm-settings).

It logs `[Worker] Started` and `[Worker] Stopped`, a failed nudge or sweep as `[Worker] Nudge Failed` and `[Worker] Sweep Failed`,
and checks in with the `jobs-sync-worker` sentry cron monitor every push sweep.
On `SIGTERM` it gives the work it took `WORKER_STOP_SECONDS`, 45, to finish, then cancels it, and a cancelled push gives its lease back.

Every run logs `[Jobs] Job Started` and `[Jobs] Job Finished` with its `duration_ms`, or `[Jobs] Job Failed` with the error.
With error tracking on, each job with a cron also checks in with a [sentry cron monitor](https://docs.sentry.io/product/crons/),
`jobs-prune-sync-operations`, `jobs-check-expiring-accounts`, `jobs-warn-disconnected-accounts`, and `jobs-prune-auth`.

Locally, one process runs every job on its cron, the same as the table, and the sync worker, until it is stopped,
a job still running when its minute comes again is left to finish, `docker compose up` runs it as `playou-jobs`:

```shell
uv run bin/jobs.sh schedule
```

Run a job by hand when you need one:

```shell
docker compose run --rm --entrypoint /app/bin/jobs.sh playou-api prune_auth
```

### Configuration

Settings are read from the environment, or from a `.env` file,
with every one of them listed in [`.env.example`](.env.example).

The ones without a usable default:

| Setting | Why |
| --- | --- |
| `DATABASE_*` | Postgres |
| `ENCRYPTION_KEYS` | Seals the platforms' tokens, accounts cannot be linked without it, make one with `uv run python -c "from src.utils import make_key; print(make_key())"` |
| `SPOTIFY_CLIENT_ID` | Spotify is not offered without it |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_API_KEY` | YouTube Music is not offered without them, see [YouTube](#youtube) |
| `APP_WEB_URL` | Where the browser is sent back after linking |
| `CORS_ORIGINS` | The web app's origins |
| `RESEND_API_KEY` | Without it, codes are logged in `DEV`, and refused in `PROD`, and no reconnect warning is sent |

> To rotate `ENCRYPTION_KEYS`, put the new key first and keep the old one after it,
> the first key seals, every key unseals, on the api and the worker alike

The api runs `APP_WORKERS` processes, one a cpu without it, set it, the cpu count ignores the container's limits,
and each opens up to `DATABASE_POOL_SIZE` + `DATABASE_MAX_OVERFLOW` connections, 5 + 3, so a replica holds up to `APP_WORKERS` × 8,
the worker 8, and a job 8, keep them under postgres' `max_connections`.
Redis gives up after `REDIS_TIMEOUT_SECONDS`, 1, and one retry, so a redis that hangs costs a request about 4 seconds.

### Logging

Everything is logged through [loguru](https://github.com/Delgan/loguru),
including uvicorn's and the other libraries' logs.
The message is a plain string, `[Area] Title Case`, with ` - ` before a reason,
and anything else goes in as keyword arguments:

```python
from src.providers import logger

logger.info(
    "[Accounts] Linked",
    platform="spotify",
    account_id=account_id,
)
```

Every request is logged once, as `[API Access Request] ...`, with its `method`, `path`, `status_code`, and `duration_ms`,
and every line of a request carries its `correlation_id`, from the `x-correlation-id` header, or generated.

> Tokens are never logged, the platforms' answers hold them as `SecretStr`, and they are sealed when stored

## Setup

The local postgres and redis listen on `5433` and `6380`, and the API on `8081`, so they run next to other projects.

### Using Docker

1. Clone [this repo](https://github.com/abdelrahman0w/playou-api)

    ```shell
    git clone https://github.com/abdelrahman0w/playou-api
    ```
1. Navigate to the repo directory

    ```shell
    cd playou-api
    ```
1. Copy the example env file, and set `ENCRYPTION_KEYS` and `SPOTIFY_CLIENT_ID` in it

    ```shell
    cp .env.example .env
    ```
1. Build and run the services

    ```shell
    docker compose up --build
    ```

This runs the API along with PostgreSQL and Redis, on [http://127.0.0.1:8081](http://127.0.0.1:8081),
reloading on changes.

### Manually

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if not installed
1. Clone [this repo](https://github.com/abdelrahman0w/playou-api)

    ```shell
    git clone https://github.com/abdelrahman0w/playou-api
    ```
1. Navigate to the repo directory

    ```shell
    cd playou-api
    ```
1. Install the dependencies

    ```shell
    uv sync --locked
    ```
1. Copy the example env file, and adjust it if needed

    ```shell
    cp .env.example .env
    ```
1. Start postgres and redis

    ```shell
    docker compose up -d playou-db playou-redis
    ```
1. Run the migrations, then the API

    ```shell
    uv run alembic upgrade head
    APP_PORT=8081 uv run bin/entrypoint.sh --dev
    ```

    > `bin/entrypoint.sh` reads the server's settings from the shell, not from `.env`, so the port is passed
1. Install the pre-commit hooks

    ```shell
    uvx pre-commit install
    ```

### Spotify

1. Create an app in the [Spotify developer dashboard](https://developer.spotify.com/dashboard), with the Web API and the Web Playback SDK
1. Add `http://127.0.0.1:8081/accounts/spotify/callback` to its redirect uris, Spotify takes loopback ips, never `localhost`
1. Put its client id in `.env` as `SPOTIFY_CLIENT_ID`, there is no secret, the link is made with PKCE
1. In development mode, only the users added in the dashboard can link their accounts

### YouTube

1. In the [Google Cloud console](https://console.cloud.google.com), create a project and enable the YouTube Data API v3
1. Configure the OAuth consent screen, add the `youtube` scope, and your account as a test user
1. Create an OAuth client of the web application type, with `http://127.0.0.1:8081/accounts/youtube/callback` as its redirect uri,
    and put its id and secret in `.env` as `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET`
1. Create an api key restricted to the YouTube Data API v3, and put it in `.env` as `YOUTUBE_API_KEY`
1. While the app is in testing, `YOUTUBE_REFRESH_TOKEN_DAYS=7`, its links last a week, and only its test users, 100 at most, can link

## Testing

Each layer is tested where its behaviour shows best:

| Layer | Tested Through |
| --- | --- |
| `routes`, `controllers` | `tests/test_routes`, http requests against the app, with the platforms mocked |
| `actions` | `tests/test_actions`, caching, rate limiting, token refresh |
| `repositories` | `tests/test_repositories`, the queries against a real postgres |
| `services`, `providers`, `utils`, `jobs` | Their own folder, directly, the services against `httpx.MockTransport` |

> Every database test runs inside a transaction that is rolled back, so nothing is left behind,
> but the concurrent refresh, which needs connections of its own, and cleans up after itself

1. Start postgres and redis

    ```shell
    docker compose up -d playou-db playou-redis
    ```

    > Without postgres, those tests are skipped and the rest still run
1. Run the tests

    ```shell
    uv run pytest
    ```

The web client's types are generated from the API's schema, `openapi.json`,
so whenever an endpoint, a request, or a response changes, write it again, then regenerate the web's types:

```shell
uv run bin/openapi.sh > openapi.json   # here
bun run api:types                      # in playou-web
```

> The schema is not served, `/docs` and `/openapi.json` stay off, it is written by the script

To lint, format, and type check:

```shell
uv run ruff check . && uv run ruff format --check . && uv run mypy
```
