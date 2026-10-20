from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from conftest import ROOT


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


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


def test_post_without_a_json_object_is_refused(service):
    status, _, _ = service.request("POST", "/notes")
    assert status == 400
    status, body = service.post_json("/notes", {"author": "oleg"})
    assert status == 400
    assert "text" in body["error"]


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
