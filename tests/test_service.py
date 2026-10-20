from __future__ import annotations

import http.client
import json
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from conftest import ROOT


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def seed(db_path, *notes: tuple[str, str, int, str]) -> None:
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.executemany(
                "INSERT INTO notes (author, text, blocked, date) VALUES (?, ?, ?, ?)", notes)
    finally:
        conn.close()


def post_with_length(service, length: str, body: bytes):
    conn = http.client.HTTPConnection("127.0.0.1", service.port, timeout=5)
    try:
        conn.putrequest("POST", "/notes")
        conn.putheader("Content-Length", length)
        conn.endheaders(body)
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read())
    finally:
        conn.close()


def test_health_answers_on_port_argument(service):
    assert service.get_json("/health") == (200, {"ok": True})


def test_health_answers_on_port_environment_variable(launch):
    service = launch(use_env_port=True)
    assert service.get_json("/health") == (200, {"ok": True})


def test_build_id_is_the_runtime_candidate_when_set(launch):
    service = launch({"FACTORY_RUNTIME_CANDIDATE": "cand-123"})
    assert service.request("GET", "/build-id") == (200, "text/plain", "cand-123")


def test_build_id_falls_back_to_git_commit(service):
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    status, content_type, body = service.request("GET", "/build-id")
    assert (status, content_type) == (200, "text/plain")
    assert body == head
    assert len(body) == 40


def test_first_post_creates_a_note(service):
    status, body = service.post_json("/notes", {"author": "oleg", "text": "shipping the invoice fix"})
    assert status == 201
    assert isinstance(body["id"], int)
    assert body == {"id": body["id"], "author": "oleg", "text": "shipping the invoice fix",
                    "blocked": False, "date": today(), "status": "created"}


def test_second_post_same_day_replaces_text_and_keeps_id(service):
    _, first = service.post_json("/notes", {"author": "oleg", "text": "first draft"})
    status, second = service.post_json("/notes", {"author": "oleg", "text": "final version"})
    assert status == 200
    assert second["status"] == "updated"
    assert second["id"] == first["id"]
    assert second["text"] == "final version"

    _, board = service.get_json("/notes")
    assert [(n["author"], n["text"]) for n in board["notes"]] == [("oleg", "final version")]


def test_board_lists_today_sorted_by_author(service):
    service.post_json("/notes", {"author": "oleg", "text": "shipping the invoice fix"})
    service.post_json("/notes", {"author": "dana", "text": "waiting on the API key"})
    status, board = service.get_json("/notes")
    assert status == 200
    assert board["date"] == today()
    assert [n["author"] for n in board["notes"]] == ["dana", "oleg"]
    assert board["blocked_count"] == 0


def test_board_shows_only_today_and_a_new_day_gets_a_new_note(service, db_path):
    seed(db_path, ("oleg", "yesterday's work", 0, "2000-01-01"))
    status, note = service.post_json("/notes", {"author": "oleg", "text": "today's work"})
    assert status == 201
    _, board = service.get_json("/notes")
    assert [(n["id"], n["text"], n["date"]) for n in board["notes"]] == [
        (note["id"], "today's work", today())]


def test_board_counts_and_flags_blocked_notes(service, db_path):
    seed(db_path, ("dana", "waiting on the API key", 1, today()),
         ("oleg", "shipping the invoice fix", 0, today()))
    _, board = service.get_json("/notes")
    assert [(n["author"], n["blocked"]) for n in board["notes"]] == [
        ("dana", True), ("oleg", False)]
    assert board["blocked_count"] == 1


def test_notes_survive_a_restart(service):
    _, oleg = service.post_json("/notes", {"author": "oleg", "text": "shipping the invoice fix"})
    _, dana = service.post_json("/notes", {"author": "dana", "text": "waiting on the API key"})
    service.restart()
    _, board = service.get_json("/notes")
    assert [(n["author"], n["id"]) for n in board["notes"]] == [
        ("dana", dana["id"]), ("oleg", oleg["id"])]


def test_database_rejects_a_second_note_for_the_same_author_and_day(service, db_path):
    service.post_json("/notes", {"author": "oleg", "text": "shipping the invoice fix"})
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO notes (author, text, date) VALUES (?, ?, ?)",
                         ("oleg", "duplicate", today()))
    finally:
        conn.close()


def test_post_without_a_body_is_refused(service):
    status, _, body = service.request("POST", "/notes")
    assert status == 400
    assert json.loads(body)["field"] == "body"


INVALID_NOTES = [
    ({"author": "", "text": "x"}, "author"),
    ({"author": "a" * 33, "text": "x"}, "author"),
    ({"author": "o leg", "text": "x"}, "author"),
    ({"author": "oleg!", "text": "x"}, "author"),
    ({"author": "ølé", "text": "x"}, "author"),
    ({"author": "oleg\n", "text": "x"}, "author"),
    ({"author": None, "text": "x"}, "author"),
    ({"text": "x"}, "author"),
    ({"author": "", "text": ""}, "author"),
    ({"author": "oleg", "text": ""}, "text"),
    ({"author": "oleg", "text": "x" * 281}, "text"),
    ({"author": "oleg"}, "text"),
    ({"author": "oleg", "text": 5}, "text"),
    ({"author": "oleg", "text": None}, "text"),
]


def assert_refused(status, body, field):
    assert status == 400
    assert body["field"] == field
    assert field in body["error"]


@pytest.mark.parametrize("payload, field", INVALID_NOTES)
def test_an_invalid_note_is_refused_naming_the_field(service, payload, field):
    status, body = service.post_json("/notes", payload)
    assert_refused(status, body, field)


@pytest.mark.parametrize("raw", [b"not json", b"[1,2]", b'"oleg"', b"null",
                                 pytest.param(b"[" * 100_000, id="deeply-nested")])
def test_a_body_that_is_not_a_json_object_is_refused(service, raw):
    status, body = post_with_length(service, str(len(raw)), raw)
    assert_refused(status, body, "body")


@pytest.mark.parametrize("author, text", [("a" * 32, "x" * 280), ("a-b_9", "x")])
def test_a_note_at_the_limits_is_accepted(service, author, text):
    status, body = service.post_json("/notes", {"author": author, "text": text})
    assert status == 201
    assert (body["author"], body["text"], body["status"]) == (author, text, "created")


def test_a_refused_replace_keeps_the_existing_note(service):
    service.post_json("/notes", {"author": "oleg", "text": "kept"})
    status, body = service.post_json("/notes", {"author": "oleg", "text": "x" * 281})
    assert_refused(status, body, "text")
    _, board = service.get_json("/notes")
    assert [(n["author"], n["text"]) for n in board["notes"]] == [("oleg", "kept")]


def test_refused_notes_write_nothing(service):
    for payload, _ in INVALID_NOTES:
        assert service.post_json("/notes", payload)[0] == 400
    for raw in (b"not json", b"[1,2]"):
        assert post_with_length(service, str(len(raw)), raw)[0] == 400
    _, board = service.get_json("/notes")
    assert (board["notes"], board["blocked_count"]) == ([], 0)


@pytest.mark.parametrize("length", ["", "abc", "-1"])
def test_post_with_an_unusable_content_length_is_refused(service, length):
    status, body = post_with_length(service, length, b"{}")
    assert status == 400
    assert "Content-Length" in body["error"]


@pytest.mark.parametrize("stall", [b"", b"POST /notes HTTP/1.1\r\nContent-Length: 100\r\n\r\n{}"])
def test_a_stalled_client_does_not_stop_the_service(service, stall):
    with socket.create_connection(("127.0.0.1", service.port)) as stalled:
        stalled.sendall(stall)
        assert service.get_json("/health") == (200, {"ok": True})


def test_a_store_failure_is_a_500_with_error(service, db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE notes")
    finally:
        conn.close()
    status, body = service.get_json("/notes")
    assert status == 500
    assert isinstance(body["error"], str)
    status, body = service.post_json("/notes", {"author": "oleg", "text": "shipping"})
    assert status == 500
    assert isinstance(body["error"], str)


def test_unknown_path_is_404_with_error(service):
    status, body = service.get_json("/nope")
    assert status == 404
    assert isinstance(body["error"], str)


def test_missing_standup_db_exits_with_message(base_env):
    env = {k: v for k, v in base_env.items() if k != "STANDUP_DB"}
    result = subprocess.run([sys.executable, "-m", "app", "--port", "0"], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "STANDUP_DB" in result.stderr


def test_missing_port_exits_with_message(base_env):
    result = subprocess.run([sys.executable, "-m", "app"], cwd=ROOT, env=base_env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "PORT" in result.stderr
