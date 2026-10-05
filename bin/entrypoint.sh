#!/usr/bin/env sh

set -eu

mode="${1:-}"

echo "INFO  Running database migrations..." >&2

alembic upgrade head

set -- \
    --host "${APP_HOST:-0.0.0.0}" \
    --port "${APP_PORT:-8080}" \
    --loop "${APP_LOOP:-uvloop}" \
    --http "${APP_HTTP:-httptools}" \
    --no-access-log

if [ "${mode}" = "--dev" ]; then
    echo "INFO  Running in dev mode, with auto reload..." >&2

    set -- "$@" --reload
else
    echo "INFO  Running in production mode..." >&2

    set -- "$@" --workers "${APP_WORKERS:-2}"
fi

exec uvicorn src.main:app "$@"
