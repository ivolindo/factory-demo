"""Start the service: python3 -m app --port <port>, or PORT from the environment."""
from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from app.server import JSONErrorH11Protocol, create_app
from app.store import NoteStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m app")
    parser.add_argument("--port", type=int, help="port to listen on (default: $PORT)")
    args = parser.parse_args(argv)

    port = args.port
    if port is None:
        try:
            port = int(os.environ["PORT"])
        except (KeyError, ValueError):
            print("error: pass --port or set PORT to a port number", file=sys.stderr)
            return 2
    db_path = os.environ.get("STANDUP_DB")
    if not db_path:
        print("error: set STANDUP_DB to the SQLite database path", file=sys.stderr)
        return 2

    # Every note is committed before its response, so cutting off a client that
    # stalls mid-request once the shutdown grace period ends loses nothing.
    uvicorn.run(create_app(NoteStore(db_path)), host="127.0.0.1", port=port,
                http=JSONErrorH11Protocol, timeout_graceful_shutdown=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
