import http.client
import os
import sys
import tempfile
import time
from pathlib import Path


FRESH_SECONDS = 30


def worker_beating() -> bool:
    health = Path(
        os.environ.get("WORKER_HEALTH_FILE")
        or Path(tempfile.gettempdir()) / "playou-worker-alive",
    )
    try:
        return time.time() - health.stat().st_mtime < FRESH_SECONDS
    except OSError:
        return False


def api_live() -> bool:
    connection = http.client.HTTPConnection(
        "127.0.0.1",
        int(os.environ.get("APP_PORT", "8080")),
        timeout=3,
    )
    try:
        connection.request("GET", "/health/live")
        return connection.getresponse().status == http.HTTPStatus.OK
    except OSError:
        return False
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(0 if worker_beating() or api_live() else 1)
