#!/usr/bin/env sh

set -e

export APP_LOG_LEVEL=ERROR

exec python -c "import json; from src.main import app; print(json.dumps(app.openapi(), indent=2))"
