#!/usr/bin/env sh

set -e

export DATABASE_STATEMENT_TIMEOUT_SECONDS="${JOBS_STATEMENT_TIMEOUT_SECONDS:-300}"

exec python -m src.jobs.main "$@"
