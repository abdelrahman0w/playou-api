# python version
ARG PYTHON_VERSION=3.14-slim

# build stage
FROM python:${PYTHON_VERSION} AS builder

# install uv
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /bin
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uvx /bin

# uv environment variables
ENV UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT="/usr/local/"

# install git (to read the commit hash)
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# set working directory
WORKDIR /app

# copy pyproject.toml and uv.lock* if not in the repo
COPY ./pyproject.toml .
COPY ./uv.lock* .

# allow installing dev dependencies
ARG INSTALL_DEV=false

# install dependencies
RUN if [ "$INSTALL_DEV" = "true" ]; \
    then uv sync --no-progress --locked --all-extras --all-groups; \
    else uv sync --no-progress --locked --all-extras --no-default-groups; \
    fi

# take commit as the app version
RUN --mount=type=bind,source=.git,target=/tmp/.git \
    git -c safe.directory='*' --git-dir=/tmp/.git rev-parse --short=12 HEAD > VERSION \
    || : > VERSION

# runtime stage
FROM python:${PYTHON_VERSION} AS runtime

# set environment variables
ENV NON_ROOT_USER=runtime \
    PYTHONUNBUFFERED=1

# install fribidi (for arabic text in images)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libfribidi0 && \
    rm -rf /var/lib/apt/lists/*

# create a non-root user
RUN groupadd -r ${NON_ROOT_USER} && \
    useradd --no-log-init -r -g ${NON_ROOT_USER} ${NON_ROOT_USER}

# copy needed binaries
COPY --from=builder \
    /usr/local/bin \
    /usr/local/bin

# copy installed dependencies
COPY --from=builder \
    /usr/local/lib/python${PYTHON_VERSION%.*}/site-packages \
    /usr/local/lib/python${PYTHON_VERSION%.*}/site-packages

# set working directory
WORKDIR /app

# copy app version file
COPY --from=builder \
    /app/VERSION .

# copy app files
COPY bin ./bin
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini .

# compile the app ahead of time
RUN python -m compileall -q src migrations

# use the non-root user
USER ${NON_ROOT_USER}:${NON_ROOT_USER}

# health check
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "/app/bin/healthcheck.py"]

# start the app
ENTRYPOINT [ "/app/bin/entrypoint.sh" ]
