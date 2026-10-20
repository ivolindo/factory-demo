"""HTTP routes, served by FastAPI under uvicorn."""
from __future__ import annotations

import html
import json
import logging
import os
import re
import sqlite3
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date as calendar_date, datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any

import h11
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect
from uvicorn.protocols.http.h11_impl import H11Protocol

from app.store import Note, NoteNotFound, NoteStore, NotToday

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


MAX_AUTHOR = 32
AUTHOR = re.compile(rf"[A-Za-z0-9_-]{{1,{MAX_AUTHOR}}}")
MAX_TEXT = 280
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class BadRequest(Exception):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def json_object(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        raise BadRequest("body", "body must be a JSON object") from None
    if not isinstance(payload, dict):
        raise BadRequest("body", "body must be a JSON object")
    return payload


def parse_note(body: bytes) -> tuple[str, str]:
    payload = json_object(body)
    author, text = payload.get("author"), payload.get("text")
    if not isinstance(author, str) or not AUTHOR.fullmatch(author):
        raise BadRequest(
            "author", f"author must be 1 to {MAX_AUTHOR} letters, digits, dashes or underscores")
    if not isinstance(text, str) or not 1 <= len(text) <= MAX_TEXT:
        raise BadRequest("text", f"text must be a string of 1 to {MAX_TEXT} characters")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        # JSON can spell a lone UTF-16 surrogate such as "\ud800", which SQLite cannot store.
        raise BadRequest("text", "text must be valid Unicode") from None
    return author, text


def parse_blocked(body: bytes) -> bool:
    blocked = json_object(body).get("blocked")
    if not isinstance(blocked, bool):
        raise BadRequest("blocked", "blocked must be true or false")
    return blocked


def parse_day(value: str) -> str:
    refused = BadRequest("date", "date must be a real calendar date written YYYY-MM-DD")
    # fromisoformat alone also accepts compact forms such as "20261020".
    if not DAY.fullmatch(value):
        raise refused
    try:
        return calendar_date.fromisoformat(value).isoformat()
    except ValueError:
        raise refused from None


def require_content_length(request: Request) -> None:
    try:
        length = int(request.headers.get("content-length", ""))
    except ValueError:
        length = -1
    if length < 0:
        raise BadRequest("body", "the body's Content-Length must be a non-negative integer")


class JSONResponse(Response):
    """JSON rendered by json.dumps, so bodies read `{"ok": true}` like the rest of the API."""

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return json.dumps(content).encode()


def error(status: HTTPStatus, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def refusal(field: str, message: str) -> dict[str, str]:
    """The body of every 400: what went wrong, and which field of the request it was."""
    return {"error": message, "field": field}


def request_target(request: Request) -> str:
    target = request.scope["raw_path"].decode("latin-1")
    query = request.scope["query_string"].decode("latin-1")
    return f"{target}?{query}" if query else target


def render_board(day: str, notes: list[Note]) -> str:
    """Today's board as a self-contained page: no script, no external asset, every value escaped."""
    entries = "\n".join(
        f"<li>{html.escape(note.author)}: {html.escape(note.text)}"
        f"{' BLOCKED' if note.blocked else ''}</li>"
        for note in notes)
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>Board {day}</title>\n</head>\n<body>\n<h1>{day}</h1>\n"
        f"<p>Blocked: {sum(note.blocked for note in notes)}</p>\n<ul>\n{entries}\n</ul>\n"
        "</body>\n</html>\n")


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
    async def board(date: str | None = None) -> JSONResponse:
        try:
            day = today() if date is None else parse_day(date)
        except BadRequest as exc:
            return JSONResponse(refusal(exc.field, str(exc)), status_code=HTTPStatus.BAD_REQUEST)
        notes = store.board(day)
        return JSONResponse({
            "date": day,
            "notes": [note.to_json() for note in notes],
            "blocked_count": sum(note.blocked for note in notes),
        })

    @app.get("/")
    async def page() -> HTMLResponse:
        day = today()
        return HTMLResponse(render_board(day, store.board(day)))

    @app.post("/notes")
    async def post_note(request: Request) -> JSONResponse:
        try:
            require_content_length(request)
            author, text = parse_note(await request.body())
        except BadRequest as exc:
            return JSONResponse(refusal(exc.field, str(exc)), status_code=HTTPStatus.BAD_REQUEST)
        note, created = store.post(author, text, today())
        return JSONResponse(
            {**note.to_json(), "status": "created" if created else "updated"},
            status_code=HTTPStatus.CREATED if created else HTTPStatus.OK,
        )

    # A non-integer id matches no route, so it gets the routing miss's 404.
    @app.post("/notes/{note_id:int}/blocked")
    async def flag_blocked(note_id: int, request: Request) -> JSONResponse:
        try:
            require_content_length(request)
            blocked = parse_blocked(await request.body())
        except BadRequest as exc:
            return JSONResponse(refusal(exc.field, str(exc)), status_code=HTTPStatus.BAD_REQUEST)
        try:
            note = store.set_blocked(note_id, blocked, today())
        except NoteNotFound:
            return error(HTTPStatus.NOT_FOUND, f"no note with id {note_id}")
        except NotToday as exc:
            return error(HTTPStatus.CONFLICT,
                         f"note {note_id} is from {exc}; only today's notes can be flagged")
        return JSONResponse(note.to_json())

    return app


class JSONErrorH11Protocol(H11Protocol):
    """uvicorn's h11 protocol, answering requests it cannot parse in the API's JSON shape.

    uvicorn refuses a malformed request head, such as an empty, negative or
    non-numeric Content-Length, before the app sees it, and its own reply is
    plain text. send_400_response is uvicorn's hook for that reply; requirements.txt
    pins the uvicorn version this override is written against.
    """

    def send_400_response(self, msg: str) -> None:
        body = json.dumps(refusal("body", "malformed HTTP request: check the request line, the "
                                          "headers, and that the body's Content-Length is a "
                                          "non-negative integer")).encode()
        headers = [(b"content-type", b"application/json"),
                   (b"content-length", str(len(body)).encode()), (b"connection", b"close")]
        for event in (h11.Response(status_code=400, headers=headers, reason=b"Bad Request"),
                      h11.Data(data=body), h11.EndOfMessage()):
            self.transport.write(self.conn.send(event))
        self.transport.close()
