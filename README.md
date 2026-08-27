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

## Usage

```sh
# read-only; also doubles as an auth smoke test
python3 cli.py list-boards

python3 cli.py create-board "Team Workload"
python3 cli.py create-stack <board_id> "Now"
python3 cli.py create-card <board_id> <stack_id> "Ship the thing" --description "..."
python3 cli.py move-card <board_id> <stack_id> <card_id> <target_stack_id>
python3 cli.py comment <card_id> "moved to done, PR merged"
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
board state, not client logic. The real logic — title lookups in
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
