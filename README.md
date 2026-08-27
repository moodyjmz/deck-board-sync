# deck-board-sync

A small, dependency-free CLI for scripting a [Nextcloud Deck](https://github.com/nextcloud/deck)
board: create boards/stacks/cards, move cards, add comments, or apply a JSON
"board spec" idempotently.

## Why this exists

Nextcloud's app passwords are **account-wide** — there's no way to scope one
to just Deck. Handing that credential to anything (an AI agent, a CI job,
whatever) means handing over your files, mail, Talk, calendar, everything.

This script doesn't fix that scoping problem — nothing can, it's a Nextcloud
limitation — but it does mean the credential only ever gets used to call
Deck's API, because that's the only thing the code here does. You hold the
credential locally; nothing else touches it.

## Setup

1. Generate an app password: Nextcloud web UI → your avatar → **Settings** →
   **Security** → "Devices & sessions" → "Create new app password". Copy it
   immediately — it's shown once.
2. Export the three required environment variables (e.g. in your shell
   profile, or a local `.envrc` if you use direnv — either way, don't commit
   them):

   ```sh
   export NC_DECK_URL="https://your-instance.example.com"
   export NC_DECK_USER="your-username"
   export NC_DECK_APP_PASSWORD="the-app-password-from-step-1"
   ```

3. Requires Python 3 only — no `pip install`, no dependencies.

## Known API quirks — don't trust label data without re-checking it

Found live, not from the docs, across three separate endpoints:

- `GET /boards` (`list_boards`) always returns `"labels": []`, regardless of
  what's actually on the board — confirmed against a board with Deck's own
  default labels, which still came back empty. `get_board()` (a single
  board GET) returns the real list.
- The nested card listing inside `GET /boards/{id}/stacks/{id}` (`list_cards`)
  always returns `"labels": null` on every card, same issue. Only a single
  card GET (`get_card()`) returns the real labels.
- The write responses from `assignLabel`/`removeLabel` themselves are
  **also** stale on this point — a real assignment can succeed while the
  response body still shows the old label state. `cli.py` re-fetches the
  card after any real label write before printing anything (`_emit_verified_card`),
  specifically because of this.

The pattern, if you're extending this: **anything involving a card's or
board's labels must come from an individual GET, never from a list endpoint
or a write response.** Every other field we've checked (ids, `stackId`,
titles, order) has been reliable everywhere we looked — this is specific to
labels, not a blanket "don't trust the API" rule. If you add a new feature
that reads label state, dry-run it against a real card and check the
printed output itself, not just the code — that's how each of these three
were actually found.

Also worth knowing: cards that are archived don't show up in `list_cards`
at all, so a title-based lookup can report "not found" for a card that
genuinely exists.

**A more serious one, found the same way:** `move_card`/`move-card`/
`move-card-by-title` were silently broken from the day they were written
until this was caught, because every prior check of them was `--dry-run`
only. The `reorder` endpoint's URL is
`PUT /boards/{boardId}/stacks/{stackId}/cards/{cardId}/reorder`, and the
request body also takes a `stackId` (the destination). Those two `stackId`s
are not the same thing to Deck's controller — the argument it actually
binds comes from the URL's `{stackId}` route segment, and the route value
wins over the body field of the same name. Passing the card's *current*
stack in the URL (natural, since that's what identifies the card's
location) and the *destination* in the body silently reorders the card
within its current stack and never moves it — 200 OK, no error, a
response payload that looks entirely plausible. **The URL's `{stackId}`
must be the destination stack**, confirmed against Deck's own source
(`CardService::reorder` in the `nextcloud/deck` repo), not just the docs.
Moral: dry-run tells you the plan is sane, not that the plan works — a
feature isn't verified until it's actually run for real, once, against a
live board.

## Usage

```sh
# read-only; also doubles as an auth smoke test
python3 cli.py list-boards

python3 cli.py create-board "Team Workload"
python3 cli.py create-stack <board_id> "Now"
python3 cli.py create-card <board_id> <stack_id> "Ship the thing" --description "..."
python3 cli.py move-card <board_id> <card_id> <target_stack_id>
python3 cli.py comment <card_id> "moved to done, PR merged"
python3 cli.py create-label <board_id> "Urgent" FF0000
python3 cli.py assign-label <board_id> <stack_id> <card_id> <label_id>
python3 cli.py remove-label <board_id> <stack_id> <card_id> <label_id>
```

Every mutating command takes `--dry-run`, which prints the exact API call it
would make (method, path, body) instead of sending it. There is deliberately
no `delete` command — deletion is destructive and out of scope until this
workflow has proven itself.

### move-card-by-title / comment-by-title

Once a board has real cards on it, finding the numeric ids for `move-card`
gets old fast. These two look things up by title instead:

```sh
python3 cli.py move-card-by-title "James" "Fix the office app" "In Progress"
python3 cli.py comment-by-title "James" "Fix the office app" "PR merged, verifying"
```

If the same card title exists in more than one stack (e.g. something
re-raised after being closed), the lookup refuses to guess — pass
`--from-stack "Backlog"` to say which one you mean. `--dry-run` prints the
*resolved* move (real ids, current and target stack titles), not just a raw
API call, since the whole point of this command is that you can't otherwise
eyeball whether the ids it found are the right ones.

Note: these lookups only see cards that show up in a plain stack listing,
which does not include archived cards. If a title isn't found and you know
the card exists, it's probably archived — use the numeric `move-card`/
`comment` commands instead, or unarchive it first.

### Colouring cards (labels)

Deck cards don't have a color field of their own — color lives on a
**label** (title + hex color), which you attach to a card. A card can carry
several labels at once.

```sh
python3 cli.py label-card-by-title "James" "Fix the office app" "Urgent" --color FF0000
python3 cli.py label-card-by-title "James" "Some other card" "Urgent"          # label already exists, no --color needed
python3 cli.py unlabel-card-by-title "James" "Fix the office app" "Urgent"
```

`label-card-by-title` creates the label first if it doesn't exist yet
(`--color` required in that case), then assigns it — matching `apply-spec`'s
create-if-missing idempotency. If the label already exists and you pass a
different `--color`, it's **not** changed — labels are board-scoped, so
recoloring one would recolor every card already carrying it; you get a
warning instead, on stderr. Assigning a label the card already has, or
removing one it doesn't have, is a no-op with a message, not an error.

There's no `delete-label` — same reasoning as no `delete-card`, but sharper
here: get the label title right the first time, since a stray label sits on
the board with no way to remove it through this CLI.

### apply-spec

For seeding a board from a JSON spec (see `examples/board-spec.example.json`):

```sh
python3 cli.py apply-spec examples/board-spec.example.json --dry-run
python3 cli.py apply-spec examples/board-spec.example.json
```

This is idempotent by title: it only creates the board/stacks/cards that
don't already exist. If a card title already exists but in a different
stack than the spec asks for, it's **skipped with a warning**, never moved —
moving a card is what `move-card` is for, explicitly.

With `--dry-run`, it prints the full resolved plan up front (including
operations on objects that don't exist yet, tagged with placeholder ids),
not just a partial simulation against what currently exists.

## Tests

No unit tests against the HTTP client — mocking Nextcloud's responses to
test glue code isn't worth much, and the real risk here is live mutation of
board state, not client logic (see "Known API quirks" above for what that
risk actually looked like in practice). The real logic — title lookups in
`by_title.py`, and `apply-spec`'s resolver in `spec_resolve.py` — are pure
functions with real test files:

```sh
python3 test_by_title.py
python3 test_resolve.py
```

No CI; run these manually before trusting `apply-spec` or `move-card-by-title`
against a real board.

## License

Apache 2.0 — see `LICENSE`.
