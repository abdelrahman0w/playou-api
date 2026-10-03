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
  - [Usage](#usage)
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
│   └── jobs.sh                     runs a single job by name
├── docs/
│   └── plan.md                     what was agreed, and what comes next
├── migrations/                     alembic migrations
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
│   │   └── main.py                 runs a job once, by name
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
| Spotify | OAuth with PKCE, no client secret | Yes | Yes | Yes | Linking, search, and pushing the library |

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
- A refused refresh marks the account `NEEDS_RECONNECT`, it is not tried again until it is linked again
- Tokens are sealed with `ENCRYPTION_KEYS`, a token sealed with a key that is gone needs reconnecting too

Refresh tokens expire too, so every account keeps when its refresh token expires,
as the platform says it when it does, `refresh_token_expires_in`, or from its lifetime, `SPOTIFY_REFRESH_TOKEN_DAYS`.

Spotify's lasts 6 months from the link, and
["refreshing an access token does not extend the refresh token's lifetime"](https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens),
it usually answers no new refresh token at all, and the stored one goes on, so nothing keeps a Spotify account past its 6 months,
its user links it again.

- A refresh only moves the expiry on when the platform says the new one, or when its refresh starts the lifetime over,
    `refresh_extends_lifetime`, which Spotify's does not
- The [`check_expiring_accounts`](#jobs) job marks the accounts past their expiry `NEEDS_RECONNECT`,
    so the web app and the search know before a request fails,
    and refreshes the ones expiring within `ACCOUNTS_KEEP_ALIVE_DAYS` on the platforms whose refresh extends it
- It emails the users whose account expires within `ACCOUNTS_EXPIRY_WARNING_DAYS` to reconnect it,
    once an expiry, in their language, linking to `APP_WEB_URL/accounts?reconnect=<platform>`,
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

### Library

The library is the app's, likes and playlists live here, and are pushed to the platforms the user turned it on for.

- Search stores what it finds in the catalog, a track once, merged across platforms by its ISRC,
    so every result has an `id` to like it or add it to a playlist by
- Nothing is deleted, an unliked track, a removed playlist, or a track removed from one is kept,
    with `removed_at` and `removed_by`, `USER` or `PLATFORM`, so the library mirrors the platforms,
    the lists leave them out, unless `include_removed=true`, and liking or adding it again brings it back
- A change and its push are stored in one transaction, a row in `sync_operations`, the outbox

```
PUT /library/likes/{id} → postgres   (the like, and its operation, one transaction)
                        ← 200
          after the response → spotify   (pushed now, the job retries what fails)
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
- Operations are claimed with `FOR UPDATE SKIP LOCKED`, so the push after a request and the job never take the same one
- `PATCH /accounts/{platform}/preferences` turns pushing likes or playlists to a platform off, or on

## Usage

### Available Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health/live` | Liveness |
| `GET` | `/health/ready` | Readiness, postgres and redis |
| `POST` | `/auth/email/code` | Emails a sign in code |
| `POST` | `/auth/email/verify` | Signs in with the code, and sets the session cookie, or answers the token with `"transport": "bearer"` |
| `POST` | `/auth/sign-out` | Ends the session |
| `GET` | `/auth/me` | The signed in user |
| `GET` | `/accounts` | The linked accounts, with what each platform can do |
| `GET` | `/accounts/{platform}/connect` | Starts linking, redirects to the platform |
| `GET` | `/accounts/{platform}/callback` | Where the platform sends the browser back, redirects to the web app |
| `DELETE` | `/accounts/{platform}` | Unlinks the account |
| `GET` | `/catalog/search?q=&limit=` | Searches every linked platform, `limit` up to 50, 20 by default |
| `GET` | `/accounts/{platform}/preferences` | What the library pushes to the platform |
| `PATCH` | `/accounts/{platform}/preferences` | Turns pushing likes or playlists on or off, `{"push_likes": false}` |
| `GET` | `/library/likes?page=&page_size=&include_removed=` | The liked tracks, newest first |
| `PUT` | `/library/likes/{track_id}` | Likes a track |
| `DELETE` | `/library/likes/{track_id}` | Unlikes it, the like is kept as removed |
| `GET` | `/library/playlists?page=&page_size=&include_removed=` | The playlists, newest first |
| `POST` | `/library/playlists` | Makes one, `{"name": "Road", "description": "Trip"}` |
| `GET` | `/library/playlists/{id}?include_removed=` | A playlist, with its tracks in order |
| `PATCH` | `/library/playlists/{id}` | Renames it, or changes its description |
| `DELETE` | `/library/playlists/{id}` | Removes it, it is kept as removed |
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

A search answers each platform's results, and its status, `OK`, `FAILED`, `TIMED_OUT`, or `NEEDS_RECONNECT`:

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
| `429` | `RATE_LIMITED` | Too many requests, see [rate limiting](#rate-limiting) |
| `502` | `PLATFORM_ERROR` | The platform responded with an error or with something unusable |
| `503` | `PLATFORM_UNAVAILABLE` | The platform could not be reached, or is limiting the requests |
| `503` | `EMAIL_UNAVAILABLE` | The code could not be sent |
| `504` | `PLATFORM_TIMEOUT` | The platform did not respond in time |

> Invalid parameters return FastAPI's default `422` validation response

### Rate Limiting

Every request is limited per signed in user, and per client ip without a session, 120 requests a minute by default,
over a sliding window in redis, shared by every replica.

The client ip is read from cloudflare's `CF-Connecting-IP` header, and from the peer address without it.
IPv6 clients are counted by their `/64`.

> The header is trusted as is, which is only safe while the origin is reachable through cloudflare alone

> The health probes are never limited, and requests go through when redis is down,
> or does not answer within `RATE_LIMIT_TIMEOUT_SECONDS`

### Jobs

Jobs are run once by name through `bin/jobs.sh`, `bin/jobs.sh <job> --help` lists their flags:

| Job | Cron | Description |
| --- | --- | --- |
| `push_library_changes` | `* * * * *` | Pushes the library's changes that are due, the ones the push after a request did not finish, `SYNC_PUSH_BATCH_SIZE` a run |
| `prune_sync_operations` | `0 1 * * *` | Drops the sync operations finished more than `SYNC_RETENTION_DAYS` ago |
| `check_expiring_accounts` | `0 3 * * *` | Marks the accounts past their refresh token's expiry `NEEDS_RECONNECT`, emails the users of the ones expiring within `ACCOUNTS_EXPIRY_WARNING_DAYS` to reconnect, once, then refreshes the ones expiring within `ACCOUNTS_KEEP_ALIVE_DAYS`, on the platforms whose refresh extends the lifetime, the soonest first, `ACCOUNTS_KEEP_ALIVE_BATCH_SIZE` a run, one at a time. A refused refresh marks the account `NEEDS_RECONNECT`, a failed one is tried again the next run |
| `prune_auth` | `30 0 * * *` | Drops the expired sessions, and the codes used or expired |

In production, each job is a schedule in dokploy, in the api's application, under **Schedules**,
with the `sh` shell, running `/app/bin/jobs.sh <job>` in the api's container, with its environment:

| Name | Cron | Command | Enabled |
| --- | --- | --- | --- |
| `push_library_changes` | `* * * * *` | Pushes the library's changes that are due, the ones the push after a request did not finish, `SYNC_PUSH_BATCH_SIZE` a run |
| `prune_sync_operations` | `0 1 * * *` | Drops the sync operations finished more than `SYNC_RETENTION_DAYS` ago |
| `push_library_changes` | `* * * * *` | `/app/bin/jobs.sh push_library_changes` | Yes |
| `prune_sync_operations` | `0 1 * * *` | `/app/bin/jobs.sh prune_sync_operations` | Yes |
| `check_expiring_accounts` | `0 3 * * *` | `/app/bin/jobs.sh check_expiring_accounts` | Yes |
| `prune_auth` | `30 0 * * *` | `/app/bin/jobs.sh prune_auth` | Yes |

> Any hour does for them, they follow the server's clock, and a day missed is made up the next one,
> the keep alive starts `ACCOUNTS_KEEP_ALIVE_DAYS` before an expiry, and an account past it is marked by the next run

> The sync jobs, `push_library_changes`, `import_libraries`, and `prune_sync_operations`, come with the library, see [the plan](docs/plan.md#sync)

Every run logs `[Jobs] Job Started` and `[Jobs] Job Finished` with its `duration_ms`, or `[Jobs] Job Failed` with the error.
With error tracking on, each job with a cron also checks in with a [sentry cron monitor](https://docs.sentry.io/product/crons/),
`jobs-push-library-changes`, `jobs-prune-sync-operations`, `jobs-check-expiring-accounts`, and `jobs-prune-auth`.

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
| `APP_WEB_URL` | Where the browser is sent back after linking |
| `CORS_ORIGINS` | The web app's origins |
| `RESEND_API_KEY` | Without it, codes are logged in `DEV`, and refused in `PROD`, and no reconnect warning is sent |

> To rotate `ENCRYPTION_KEYS`, put the new key first and keep the old one after it,
> the first key seals, every key unseals

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

1. Create an app in the [Spotify developer dashboard](https://developer.spotify.com/dashboard), with the Web API
1. Add `http://127.0.0.1:8081/accounts/spotify/callback` to its redirect uris, Spotify takes loopback ips, never `localhost`
1. Put its client id in `.env` as `SPOTIFY_CLIENT_ID`, there is no secret, the link is made with PKCE
1. In development mode, only the users added in the dashboard can link their accounts

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

To lint, format, and type check:

```shell
uv run ruff check . && uv run ruff format --check . && uv run mypy
```
