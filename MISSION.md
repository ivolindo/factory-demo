# Mission

**Derived from:** PRD.md
**Last reconciled with it:** 2026-10-20

## What Standup Notes is

Standup Notes is a small web service where each member of one team posts one
short note per day, the team reads today's board, and anyone can flag their own
note as blocked. A team lead opens the board and sees in one glance who is
blocked. Notes survive a restart of the service.

It is built for exactly one team, served from one process, with one local SQLite
file as its only storage. The author field is trusted input, not an identity.

## Who it is for

- A team member who wants to post a one-line note and mark it blocked or unblocked.
- A team lead who wants to read today's board and the count of blocked people.

Standup Notes is not a chat tool, a task tracker, or a wiki.

## Core capabilities (in scope)

The factory may accept issues in these areas.

**Notes**
- Post a note for an author for today; a second post the same day replaces the text and keeps the id.
- Set or clear the blocked flag on a note.
- Validate author (1 to 32 chars, letters, digits, dash, underscore) and text (1 to 280 chars), returning 400 naming the field.

**Board**
- List today's notes sorted by author with a count of blocked notes.
- List another day's notes by date.
- An optional plain HTML page at `/` that renders today's board.

**Operations**
- `GET /health` returns 200 `{ "ok": true }`.
- `GET /build-id` returns the build identity from the environment, or the git commit.
- Start with one command, port from an argument or environment variable, ready within 5 seconds.
- Unit tests run with one command in under 30 seconds; CI runs them on every pull request.

## Out of scope -- the factory must never build this

**Identity**
- Authentication, login, sessions, API keys, or user accounts of any kind.
- Permissions or roles. Everyone may do everything.

**Scope creep**
- Multiple teams, workspaces, or tenants.
- Editing or deleting notes from previous days.
- Deleting notes at all.
- Comments, reactions, threads, or attachments on a note.

**Integrations**
- Notifications of any kind: email, Slack, Telegram, push.
- Importing or exporting notes to other systems.

**Stack**
- A front-end build step, JavaScript framework, or bundler.
- Any database other than the local SQLite file.
- A background worker, scheduler, or queue.

## Hard invariants -- not tunable by any issue

1. **One note per author per day.** The board must never show two notes for the same author on the same date.
2. **Notes survive a restart.** Every note and flag is written to the SQLite file before the request returns.
3. **The storage path comes from the environment.** The service never writes outside the configured database path.
4. **The factory cannot modify governance files.** `MISSION.md`, `FACTORY_RULES.md` and `engineering.md` are the constitution. A PR touching any of them is an automatic reject.
5. **The factory cannot modify its own judge.** `harness/` and `.factory/holdout/` define what "working" means here. Adding an assertion is always welcome; removing or loosening one is a human decision, always.

## Allowed evolutions

- Adding tests, type hints, and docstrings freely.
- Improving the optional HTML board page without adding a build step.

## Definition of done

**Gate 1 -- static checks and tests pass.** `python harness/ci.py`

**Gate 2 -- the API is usable from curl alone.** Every route works with plain JSON and needs no documentation beyond the route list in `PRD.md`.

**Gate 3 -- the end-to-end path passes as a real user.**

1. Start the service on a free port with a fresh database path.
2. Post a note as `oleg` and a note as `dana`.
3. Mark `dana`'s note blocked.
4. Restart the service with the same database path.
5. `GET /notes` shows both notes, sorted by author, with a blocked count of 1.

This runs on every change that touches runnable code, including ones that "seem unrelated".

## Open questions -- decisions nobody has made yet

The factory may propose an answer to any of them, build against it, and record what it assumed. The merge is then held for a human.

- **Q2** Should `GET /notes` for a date with no notes return an empty list with 200, or 404?
- **Q3** Which timezone defines "today": UTC always, or a configurable one? The PRD says UTC.

**Except these, which do stop the factory** -- they are irreversible rather than open:

- Anything about who may act as whom. There is no identity in this product.
- Migrating or deleting the SQLite file or changing its schema in a way that loses notes.

## Decisions

- 2026-10-20 **Which web framework?** FastAPI, served by uvicorn. Those two packages are the one allowed framework dependency; declare them in `requirements.txt`. The service must still start with `python3 -m app --port <port>` and keep every route and response shape unchanged.
- 2026-10-20 **Which date format?** `YYYY-MM-DD`, UTC, as the PRD states.

## What the factory does NOT own -- permanently human

- Whether the board page looks clear at a glance.
- Whether the error messages read well to a person.
- Whether 280 characters is the right limit.

The factory owns the routes, the validation rules, the persistence, and the one-note-per-day rule. That is the layer whose correctness can be asserted.
