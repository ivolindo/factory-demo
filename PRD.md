# Standup Notes — product requirements

**Author:** Oleg Ruchovets
**Date:** 2026-10-20
**Status:** draft for the first factory run

## Problem

A small team posts a one-line standup each morning in chat. By the afternoon the
lines are buried, nobody can see who is blocked, and yesterday's notes are gone.

## Why now

We are trialling an AI software factory and need a product small enough to build
in one afternoon yet real enough that a user journey can fail.

## What it is

A single-user-per-team web service where each person posts one short note per
day, the team reads today's board, and anyone can flag their own note as blocked.
Notes survive a restart of the service.

## Users

- A team member: posts a note, marks it blocked or unblocked.
- A team lead: reads today's board and sees who is blocked at a glance.

## Functional requirements

1. **Post a note.** `POST /notes` with JSON `{ "author": "oleg", "text": "shipping the invoice fix" }`.
   Returns the stored note with an id, the author, the text, `blocked: false`, and the
   date it was posted (UTC date, `YYYY-MM-DD`).
2. **One note per author per day.** A second post by the same author on the same day
   replaces the text of the existing note and keeps its id. The response says it was
   updated, not created.
3. **Today's board.** `GET /notes` returns today's notes sorted by author, plus a
   count of blocked notes. `GET /notes?date=YYYY-MM-DD` returns another day.
4. **Flag blocked.** `POST /notes/{id}/blocked` with `{ "blocked": true }` or `false`
   sets the flag. The board count changes accordingly.
5. **Validation.** Author is 1 to 32 characters, letters, digits, dash, underscore.
   Text is 1 to 280 characters. Anything else returns 400 with a message that names
   the field.
6. **Persistence.** Notes are stored in a local SQLite file whose path comes from an
   environment variable. A restart of the service keeps every note and flag.
7. **Operational endpoints.** `GET /health` returns 200 with `{ "ok": true }`.
   `GET /build-id` returns the build identity string the environment provides, or
   the git commit when none is provided.

## Non-functional requirements

- Python 3.12, standard library plus one small web framework at most. No front-end
  build step. A plain HTML page at `/` that renders today's board is welcome but
  optional.
- Starts with one command that takes the port from an argument or environment
  variable. Ready to serve within 5 seconds.
- Unit tests run with one command and finish in under 30 seconds.
- CI on GitHub Actions runs the tests on every pull request.

## Out of scope for this release

- Authentication or user accounts. The author field is trusted.
- Multiple teams or workspaces.
- Editing notes from previous days.
- Notifications, chat integrations, email.
- Deleting notes.

## Acceptance

A user can start the service, post two notes from two authors, mark one blocked,
restart the service, and see both notes with exactly one blocked on today's board.
