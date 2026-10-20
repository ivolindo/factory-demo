"""Start the service: python3 -m app --port <port>, or PORT from the environment."""
from __future__ import annotations

import argparse
import os
import signal
import sys

from app.server import StandupServer
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

    store = NoteStore(db_path)
    server = StandupServer(port, store)
    # Turn SIGTERM into a clean exit so the database connection is closed.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print(f"Standup Notes listening on http://127.0.0.1:{port}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
