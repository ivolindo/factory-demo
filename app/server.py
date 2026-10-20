"""HTTP routes, served by the standard library's http.server."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from app.store import NoteStore

REPO_ROOT = Path(__file__).resolve().parent.parent


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def build_id() -> str | None:
    candidate = os.environ.get("FACTORY_RUNTIME_CANDIDATE")
    if candidate:
        return candidate
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


class BadRequest(Exception):
    pass


def parse_note(body: bytes) -> tuple[str, str]:
    try:
        payload = json.loads(body)
    except ValueError:
        raise BadRequest("body must be a JSON object") from None
    if not isinstance(payload, dict):
        raise BadRequest("body must be a JSON object")
    for field in ("author", "text"):
        if not isinstance(payload.get(field), str):
            raise BadRequest(f"{field} must be a string")
    return payload["author"], payload["text"]


class Handler(BaseHTTPRequestHandler):
    server: "StandupServer"

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/health":
            self._send_json(HTTPStatus.OK, {"ok": True})
        elif path == "/build-id":
            identity = build_id()
            if identity is None:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR,
                                {"error": "no build identity available"})
            else:
                self._send(HTTPStatus.OK, "text/plain; charset=utf-8", identity.encode())
        elif path == "/notes":
            date = today()
            notes = self.server.store.board(date)
            self._send_json(HTTPStatus.OK, {
                "date": date,
                "notes": [note.to_json() for note in notes],
                "blocked_count": sum(note.blocked for note in notes),
            })
        else:
            self._not_found()

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/notes":
            self._not_found()
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            author, text = parse_note(self.rfile.read(length))
        except BadRequest as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        note, created = self.server.store.post(author, text, today())
        self._send_json(
            HTTPStatus.CREATED if created else HTTPStatus.OK,
            {**note.to_json(), "status": "created" if created else "updated"},
        )

    def _not_found(self) -> None:
        self._send_json(HTTPStatus.NOT_FOUND, {"error": f"no route for {self.path}"})

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        self._send(status, "application/json", json.dumps(payload).encode())

    def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class StandupServer(HTTPServer):
    def __init__(self, port: int, store: NoteStore) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.store = store
