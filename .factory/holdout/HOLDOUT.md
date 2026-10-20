# Holdout scenarios

Independent scenarios that combine Standup Notes behaviour in ways the journeys
do not. The verification environment runs these from a fresh database; the builder
does not read them.

## Three authors, one flips twice, one restart in the middle

1. Post notes as `ana`, `ben` and `cleo`.
2. Mark `ben` blocked, then mark `ben` unblocked, then mark `cleo` blocked.
3. Restart the service with the same database path.
4. `GET /notes`. Three notes in the order `ana`, `ben`, `cleo`. Exactly `cleo` is
   blocked. The blocked count is 1.

## Replacing a blocked note keeps it blocked and keeps its id

1. Post a note as `ana` with the text `old`. Mark it blocked.
2. Post again as `ana` with the text `new`.
3. The response says updated and returns the same id. `GET /notes` shows one note
   for `ana`, text `new`, still `blocked: true`, blocked count 1.

## Yesterday is not today

1. `GET /notes?date=2026-01-01`. An empty board with blocked count 0.
2. Post a note as `ana` today.
3. `GET /notes?date=2026-01-01` is still empty. `GET /notes` shows `ana`.

## Boundary values are accepted, one past them is not

1. Post a note as an author of exactly 32 characters with text of exactly 280
   characters. The response is a created note.
2. Post a note as an author of 33 characters. 400, naming `author`.
3. Post a note as `a-b_9` with one character of text. Created.
4. `GET /notes` shows exactly two notes.

## Health and build identity are always available

1. `GET /health` returns 200 and `{ "ok": true }` before any note exists.
2. `GET /build-id` returns a nonempty string that equals the `FACTORY_RUNTIME_CANDIDATE`
   environment variable when it is set.
