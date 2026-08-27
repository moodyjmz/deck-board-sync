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
board state, not client logic. The one piece of real logic — `apply-spec`'s
resolver, in `spec_resolve.py` — is a pure function and has a real test
file:

```sh
python3 test_resolve.py
```

No CI; run it manually before trusting `apply-spec` against a real board.

## License

Apache 2.0 — see `LICENSE`.
