"""SQLite storage for notes. The database file is the service's only state."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    author  TEXT    NOT NULL,
    text    TEXT    NOT NULL,
    blocked INTEGER NOT NULL DEFAULT 0,
    date    TEXT    NOT NULL,
    UNIQUE (author, date)
)
"""


@dataclass(frozen=True)
class Note:
    id: int
    author: str
    text: str
    blocked: bool
    date: str

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "author": self.author,
            "text": self.text,
            "blocked": self.blocked,
            "date": self.date,
        }


class NoteStore:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path)
        with self._conn:
            self._conn.execute(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def post(self, author: str, text: str, date: str) -> tuple[Note, bool]:
        """Create the author's note for `date`, or replace its text. True when created."""
        with self._conn:
            created = self._conn.execute(
                "INSERT INTO notes (author, text, date) VALUES (?, ?, ?)"
                " ON CONFLICT (author, date) DO NOTHING",
                (author, text, date),
            ).rowcount == 1
            if not created:
                self._conn.execute(
                    "UPDATE notes SET text = ? WHERE author = ? AND date = ?",
                    (text, author, date),
                )
            row = self._conn.execute(
                "SELECT id, author, text, blocked, date FROM notes"
                " WHERE author = ? AND date = ?",
                (author, date),
            ).fetchone()
        return _note(row), created

    def board(self, date: str) -> list[Note]:
        rows = self._conn.execute(
            "SELECT id, author, text, blocked, date FROM notes"
            " WHERE date = ? ORDER BY author",
            (date,),
        ).fetchall()
        return [_note(row) for row in rows]


def _note(row: tuple) -> Note:
    id_, author, text, blocked, date = row
    return Note(id=id_, author=author, text=text, blocked=bool(blocked), date=date)
