#!/usr/bin/env python3
"""CLI for the Deck client. Credentials come only from the environment:

    NC_DECK_URL            e.g. https://cloud.example.com
    NC_DECK_USER            your Nextcloud username
    NC_DECK_APP_PASSWORD    an app password from Settings -> Security ->
                             Devices & sessions (NOT your account password;
                             note this is account-wide, not Deck-scoped --
                             Nextcloud has no per-app token scoping)

Every mutating subcommand takes --dry-run, which prints the exact API
call(s) it would make without sending them. There is no delete command --
deliberate, deletion is destructive and out of scope until this workflow is
proven out.
"""

import argparse
import json
import os
import sys

from deck_client import DeckClient, DeckAPIError
from spec_resolve import resolve


def get_client(args):
    url = os.environ.get("NC_DECK_URL")
    user = os.environ.get("NC_DECK_USER")
    app_password = os.environ.get("NC_DECK_APP_PASSWORD")
    missing = [name for name, val in (
        ("NC_DECK_URL", url), ("NC_DECK_USER", user), ("NC_DECK_APP_PASSWORD", app_password),
    ) if not val]
    if missing:
        sys.exit(f"Missing required environment variable(s): {', '.join(missing)}")
    return DeckClient(url, user, app_password, allow_insecure=args.allow_insecure)


def emit(result):
    print(json.dumps(result, indent=2))


def cmd_list_boards(args, client):
    emit(client.list_boards())


def cmd_create_board(args, client):
    emit(client.create_board(args.title, color=args.color, dry_run=args.dry_run))


def cmd_create_stack(args, client):
    emit(client.create_stack(args.board_id, args.title, order=args.order, dry_run=args.dry_run))


def cmd_create_card(args, client):
    emit(client.create_card(
        args.board_id, args.stack_id, args.title,
        description=args.description, duedate=args.duedate, order=args.order, dry_run=args.dry_run,
    ))


def cmd_move_card(args, client):
    emit(client.move_card(
        args.board_id, args.stack_id, args.card_id, args.target_stack_id, order=args.order, dry_run=args.dry_run,
    ))


def cmd_comment(args, client):
    emit(client.add_comment(args.card_id, args.message, dry_run=args.dry_run))


def _current_state(client, spec):
    boards = client.list_boards()
    board = next((b for b in boards if b["title"] == spec["board"]["title"]), None)
    if board is None:
        return {"board": None, "stacks": [], "cards": []}

    stacks = client.list_stacks(board["id"])
    cards = []
    for s in stacks:
        for c in client.list_cards(board["id"], s["id"]):
            c = dict(c)
            c["stackTitle"] = s["title"]
            cards.append(c)
    return {"board": board, "stacks": stacks, "cards": cards}


def cmd_apply_spec(args, client):
    with open(args.spec_file) as f:
        spec = json.load(f)

    state = _current_state(client, spec)
    ops = resolve(state, spec)

    if args.dry_run:
        emit(ops)
        return

    id_map = {}

    def resolve_id(value):
        return id_map[value] if isinstance(value, str) and value.startswith("new:") else value

    for op in ops:
        kind = op["op"]
        if kind == "skip_card_wrong_stack":
            print(
                f"WARNING: card {op['title']!r} already exists in stack {op['existing_stack']!r}, "
                f"spec wants {op['target_stack']!r} -- skipped, not moved. Use move-card to move it explicitly.",
                file=sys.stderr,
            )
            continue
        if kind == "create_board":
            result = client.create_board(op["title"], color=op.get("color", "0082C9"))
        elif kind == "create_stack":
            result = client.create_stack(resolve_id(op["board_id"]), op["title"])
        elif kind == "create_card":
            result = client.create_card(
                resolve_id(op["board_id"]), resolve_id(op["stack_id"]), op["title"],
                description=op.get("description"),
            )
        else:
            raise AssertionError(f"unhandled op kind: {kind}")
        id_map[op["id"]] = result["id"]
        print(f"created {kind} -> id {result['id']}: {op.get('title')}")


def build_parser():
    p = argparse.ArgumentParser(description="Nextcloud Deck sync CLI (stdlib-only, credentials via env vars)")
    p.add_argument("--allow-insecure", action="store_true", help="allow a non-https NC_DECK_URL (local/dev only)")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("list-boards", help="list boards (read-only, doubles as an auth smoke test)")
    sp.set_defaults(func=cmd_list_boards)

    sp = sub.add_parser("create-board")
    sp.add_argument("title")
    sp.add_argument("--color", default="0082C9")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_create_board)

    sp = sub.add_parser("create-stack")
    sp.add_argument("board_id", type=int)
    sp.add_argument("title")
    sp.add_argument("--order", type=int, default=999)
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_create_stack)

    sp = sub.add_parser("create-card")
    sp.add_argument("board_id", type=int)
    sp.add_argument("stack_id", type=int)
    sp.add_argument("title")
    sp.add_argument("--description")
    sp.add_argument("--duedate")
    sp.add_argument("--order", type=int, default=999)
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_create_card)

    sp = sub.add_parser("move-card")
    sp.add_argument("board_id", type=int)
    sp.add_argument("stack_id", type=int)
    sp.add_argument("card_id", type=int)
    sp.add_argument("target_stack_id", type=int)
    sp.add_argument("--order", type=int, default=999)
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_move_card)

    sp = sub.add_parser("comment")
    sp.add_argument("card_id", type=int)
    sp.add_argument("message")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_comment)

    sp = sub.add_parser("apply-spec", help="create whatever a board-spec JSON file describes that doesn't already exist")
    sp.add_argument("spec_file")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_apply_spec)

    return p


def main():
    args = build_parser().parse_args()
    client = get_client(args)
    try:
        args.func(args, client)
    except DeckAPIError as e:
        sys.exit(f"Deck API error {e.status}: {e.body}")


if __name__ == "__main__":
    main()
