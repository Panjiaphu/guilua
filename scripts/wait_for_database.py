import os
import socket
import sys
import time
from urllib.parse import urlparse


def main():
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1

    parsed = urlparse(database_url)
    host = parsed.hostname
    port = parsed.port or 5432
    if not host:
        print("DATABASE_URL does not include a hostname.", file=sys.stderr)
        return 1

    timeout_seconds = int(os.getenv("DATABASE_WAIT_TIMEOUT", "60"))
    deadline = time.time() + timeout_seconds
    last_error = None

    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=5):
                print(f"Database host is reachable: {host}:{port}")
                return 0
        except OSError as exc:
            last_error = exc
            print(f"Waiting for database {host}:{port}: {exc}")
            time.sleep(3)

    print(f"Database host is not reachable after {timeout_seconds}s: {host}:{port}", file=sys.stderr)
    if last_error:
        print(f"Last error: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
