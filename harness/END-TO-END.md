# Runtime scenarios

Journeys a real user of Standup Notes takes. Shared runtime verification owns
execution and evidence. Each journey starts from a fresh database.

## A team posts notes and the lead sees who is blocked

1. Post a note as `oleg` with the text `shipping the invoice fix`.
2. Post a note as `dana` with the text `waiting on the API key`.
3. `GET /notes`. Two notes appear, sorted by author (`dana` before `oleg`), both
   with `blocked: false`, and the blocked count is 0.
4. Set `dana`'s note to blocked.
5. `GET /notes` again. `dana`'s note shows `blocked: true`, `oleg`'s does not, and
   the blocked count is 1.

**What would make this fail:** a note missing from the board, the order wrong, the
flag landing on the wrong note, or a count that does not change.

## The board survives a restart

1. Post a note as `oleg` and a note as `dana`, and mark `dana` blocked.
2. Restart the service with the same database path.
3. `GET /notes`. Both notes are still there with their ids unchanged, exactly
   `dana` is blocked, and the blocked count is 1.

**What would make this fail:** anything held only in memory, an id that changes
across restarts, or a flag that resets.

## A second post the same day replaces, never duplicates

1. Post a note as `oleg` with the text `first draft`. Note the returned id.
2. Post again as `oleg` with the text `final version`. The response says the note
   was updated and returns the same id.
3. `GET /notes`. Exactly one note for `oleg`, with the text `final version`.

**What would make this fail:** two entries for `oleg`, a new id, or the old text.

## Bad input is refused and names the field

1. Post a note with an empty author. The response is 400 and the message names `author`.
2. Post a note as `oleg` with 281 characters of text. The response is 400 and the message names `text`.
3. `GET /notes`. The board is empty and the blocked count is 0.

**What would make this fail:** a 500, a 400 that does not say which field, or a bad
note that still lands on the board.
