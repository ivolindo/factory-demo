"""HTTP routes, served by FastAPI under uvicorn."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any

import h11
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect
from uvicorn.protocols.http.h11_impl import H11Protocol

from app.store import NoteStore

REPO_ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("uvicorn.error")


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


def require_content_length(request: Request) -> None:
    try:
        length = int(request.headers.get("content-length", ""))
    except ValueError:
        length = -1
    if length < 0:
        raise BadRequest("Content-Length must be a non-negative integer")


class JSONResponse(Response):
    """JSON rendered by json.dumps, so bodies read `{"ok": true}` like the rest of the API."""

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return json.dumps(content).encode()


def error(status: HTTPStatus, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def request_target(request: Request) -> str:
    target = request.scope["raw_path"].decode("latin-1")
    query = request.scope["query_string"].decode("latin-1")
    return f"{target}?{query}" if query else target


def create_app(store: NoteStore) -> FastAPI:
    """The service's routes over `store`, which the app closes when the server shuts down."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        store.close()

    app = FastAPI(
        lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
        redirect_slashes=False, default_response_class=JSONResponse,
    )

    @app.exception_handler(HTTPException)
    async def no_route(request: Request, _: HTTPException) -> JSONResponse:
        # Every routing miss, including a known path with another method, is a 404.
        return error(HTTPStatus.NOT_FOUND, f"no route for {request_target(request)}")

    @app.exception_handler(ClientDisconnect)
    async def client_left(_: Request, __: ClientDisconnect) -> Response:
        # The client hung up before sending its whole body; nobody reads this reply.
        return Response(status_code=HTTPStatus.BAD_REQUEST)

    @app.exception_handler(sqlite3.Error)
    async def store_failed(_: Request, exc: sqlite3.Error) -> JSONResponse:
        log.error("store failed: %r", exc)
        return error(HTTPStatus.INTERNAL_SERVER_ERROR, "the note store failed")

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    # A plain def runs in a worker thread, so the git lookup does not stall other requests.
    @app.get("/build-id")
    def build_identity() -> Response:
        identity = build_id()
        if identity is None:
            return error(HTTPStatus.INTERNAL_SERVER_ERROR, "no build identity available")
        return PlainTextResponse(identity)

    # The store's SQLite connection belongs to the thread that opened it, so every
    # route that touches the store is async and runs on the server's own thread.
    @app.get("/notes")
    async def board() -> dict:
        date = today()
        notes = store.board(date)
        return {
            "date": date,
            "notes": [note.to_json() for note in notes],
            "blocked_count": sum(note.blocked for note in notes),
        }

    @app.post("/notes")
    async def post_note(request: Request) -> JSONResponse:
        try:
            require_content_length(request)
            author, text = parse_note(await request.body())
        except BadRequest as exc:
            return error(HTTPStatus.BAD_REQUEST, str(exc))
        note, created = store.post(author, text, today())
        return JSONResponse(
            {**note.to_json(), "status": "created" if created else "updated"},
            status_code=HTTPStatus.CREATED if created else HTTPStatus.OK,
        )

    return app


class JSONErrorH11Protocol(H11Protocol):
    """uvicorn's h11 protocol, answering requests it cannot parse in the API's JSON shape.

    uvicorn refuses a malformed request head, such as an empty, negative or
    non-numeric Content-Length, before the app sees it, and its own reply is
    plain text. send_400_response is uvicorn's hook for that reply; requirements.txt
    pins the uvicorn version this override is written against.
    """

    def send_400_response(self, msg: str) -> None:
        body = json.dumps({"error": "malformed HTTP request: check the request line, the "
                                    "headers, and that Content-Length is a non-negative integer"}
                          ).encode()
        headers = [(b"content-type", b"application/json"),
                   (b"content-length", str(len(body)).encode()), (b"connection", b"close")]
        for event in (h11.Response(status_code=400, headers=headers, reason=b"Bad Request"),
                      h11.Data(data=body), h11.EndOfMessage()):
            self.transport.write(self.conn.send(event))
        self.transport.close()
