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
from by_title import find_board, find_card, find_label, find_stack


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


def _fetch_board_state(client, board_title):
    """Boards/stacks/cards for one board, by title. cards each carry a
    "stackTitle" key attached here, since list_cards doesn't include it.
    board is None if no board has this title -- callers decide what that
    means (apply-spec: needs creating; the *-by-title commands: fatal).
    Note: archived cards are not included -- list_cards only returns what
    a plain stack GET returns, which excludes them (confirmed against a
    live board, not assumed).
    """
    board = find_board(client.list_boards(), board_title)
    if board is None:
        return {"board": None, "stacks": [], "cards": []}
    board = client.get_board(board["id"])  # list_boards() doesn't populate labels; a single GET does

    stacks = client.list_stacks(board["id"])
    cards = []
    for s in stacks:
        for c in client.list_cards(board["id"], s["id"]):
            c = dict(c)
            c["stackTitle"] = s["title"]
            cards.append(c)
    return {"board": board, "stacks": stacks, "cards": cards}


def cmd_move_card_by_title(args, client):
    state = _fetch_board_state(client, args.board_title)
    if state["board"] is None:
        sys.exit(f"No board titled {args.board_title!r}")
    card = find_card(state["cards"], args.card_title, from_stack=args.from_stack)
    if card is None:
        scope = f" in stack {args.from_stack!r}" if args.from_stack else ""
        sys.exit(f"No card titled {args.card_title!r}{scope} on board {args.board_title!r} "
                  f"(note: archived cards aren't visible to this lookup)")
    stack = find_stack(state["stacks"], args.target_stack_title)
    if stack is None:
        sys.exit(f"No stack titled {args.target_stack_title!r} on board {args.board_title!r}")

    if args.dry_run:
        print(f"would move card {card['id']} {card['title']!r} "
              f"from stack {card['stackId']} {card.get('stackTitle')!r} "
              f"to stack {stack['id']} {stack['title']!r} (board {state['board']['id']})")
        return

    emit(client.move_card(state["board"]["id"], card["stackId"], card["id"], stack["id"], order=args.order))


def cmd_comment_by_title(args, client):
    state = _fetch_board_state(client, args.board_title)
    if state["board"] is None:
        sys.exit(f"No board titled {args.board_title!r}")
    card = find_card(state["cards"], args.card_title, from_stack=args.from_stack)
    if card is None:
        scope = f" in stack {args.from_stack!r}" if args.from_stack else ""
        sys.exit(f"No card titled {args.card_title!r}{scope} on board {args.board_title!r} "
                  f"(note: archived cards aren't visible to this lookup)")

    if args.dry_run:
        print(f"would comment on card {card['id']} {card['title']!r}: {args.message!r}")
        return

    emit(client.add_comment(card["id"], args.message))


def cmd_create_label(args, client):
    emit(client.create_label(args.board_id, args.title, args.color, dry_run=args.dry_run))


def cmd_assign_label(args, client):
    emit(client.assign_label(args.board_id, args.stack_id, args.card_id, args.label_id, dry_run=args.dry_run))


def cmd_remove_label(args, client):
    emit(client.remove_label(args.board_id, args.stack_id, args.card_id, args.label_id, dry_run=args.dry_run))


def _resolve_card_and_label(args, client, require_label=False):
    """Shared lookup for the label-card-by-title / unlabel-card-by-title
    commands. Exits with a clear message on any not-found case. Returns
    (state, card, label) -- label is None if it doesn't exist yet and
    require_label is False (the caller is about to create it).

    The card is re-fetched individually after the title lookup: cards from
    _fetch_board_state come via list_cards, which -- like list_boards --
    always returns "labels": null regardless of what's actually assigned
    (confirmed live). Only a single-card GET returns real label data, and
    the "already has this label" check needs that to not be silently wrong.
    """
    state = _fetch_board_state(client, args.board_title)
    if state["board"] is None:
        sys.exit(f"No board titled {args.board_title!r}")

    card = find_card(state["cards"], args.card_title, from_stack=args.from_stack)
    if card is None:
        scope = f" in stack {args.from_stack!r}" if args.from_stack else ""
        sys.exit(f"No card titled {args.card_title!r}{scope} on board {args.board_title!r} "
                  f"(note: archived cards aren't visible to this lookup)")
    stack_title = card.get("stackTitle")
    card = client.get_card(state["board"]["id"], card["stackId"], card["id"])
    card["stackTitle"] = stack_title

    label = find_label(state["board"]["labels"], args.label_title)
    if label is None and require_label:
        sys.exit(f"No label titled {args.label_title!r} on board {args.board_title!r}")

    return state, card, label


def _emit_verified_card(client, board_id, stack_id, card_id):
    """Print the card's real current state via a fresh GET, not whatever
    assign_label/remove_label returned -- those write responses carry
    stale label data (confirmed live: a real assignment succeeded but the
    write response still showed an empty labels array), same issue as
    list_cards/list_boards.
    """
    emit(client.get_card(board_id, stack_id, card_id))


def cmd_label_card_by_title(args, client):
    state, card, label = _resolve_card_and_label(args, client, require_label=False)
    existing_ids = {l["id"] for l in (card.get("labels") or [])}

    if label is not None:
        if args.color and label["color"].lower() != args.color.lower():
            print(f"WARNING: label {args.label_title!r} already exists with color {label['color']!r} -- "
                  f"not changing it to {args.color!r}, that would recolor every card carrying it. "
                  f"Remove --color, or use a different label title.", file=sys.stderr)
        if label["id"] in existing_ids:
            print(f"Card {card['title']!r} already has label {args.label_title!r} -- nothing to do.")
            return
        if args.dry_run:
            print(f"would assign existing label {label['id']} {label['title']!r} ({label['color']}) "
                  f"to card {card['id']} {card['title']!r}")
            return
        client.assign_label(state["board"]["id"], card["stackId"], card["id"], label["id"])
        _emit_verified_card(client, state["board"]["id"], card["stackId"], card["id"])
        return

    if not args.color:
        sys.exit(f"Label {args.label_title!r} doesn't exist on board {args.board_title!r} yet -- "
                  f"pass --color to create it (hex, e.g. FF0000)")

    if args.dry_run:
        print(f"would create label {args.label_title!r} (color {args.color}) on board {state['board']['id']}, "
              f"then assign to card {card['id']} {card['title']!r}")
        return

    new_label = client.create_label(state["board"]["id"], args.label_title, args.color)
    client.assign_label(state["board"]["id"], card["stackId"], card["id"], new_label["id"])
    _emit_verified_card(client, state["board"]["id"], card["stackId"], card["id"])


def cmd_unlabel_card_by_title(args, client):
    state, card, label = _resolve_card_and_label(args, client, require_label=True)
    existing_ids = {l["id"] for l in (card.get("labels") or [])}

    if label["id"] not in existing_ids:
        print(f"Card {card['title']!r} doesn't have label {args.label_title!r} -- nothing to do.")
        return

    if args.dry_run:
        print(f"would remove label {label['id']} {label['title']!r} from card {card['id']} {card['title']!r}")
        return

    client.remove_label(state["board"]["id"], card["stackId"], card["id"], label["id"])
    _emit_verified_card(client, state["board"]["id"], card["stackId"], card["id"])


def cmd_apply_spec(args, client):
    with open(args.spec_file) as f:
        spec = json.load(f)

    state = _fetch_board_state(client, spec["board"]["title"])
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

    sp = sub.add_parser("move-card-by-title", help="move a card by looking up board/card/target-stack titles instead of numeric ids")
    sp.add_argument("board_title")
    sp.add_argument("card_title")
    sp.add_argument("target_stack_title")
    sp.add_argument("--from-stack", help="disambiguate when the same card title exists in more than one stack")
    sp.add_argument("--order", type=int, default=999)
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_move_card_by_title)

    sp = sub.add_parser("comment-by-title", help="comment on a card by looking up board/card titles instead of numeric ids")
    sp.add_argument("board_title")
    sp.add_argument("card_title")
    sp.add_argument("message")
    sp.add_argument("--from-stack", help="disambiguate when the same card title exists in more than one stack")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_comment_by_title)

    sp = sub.add_parser("create-label")
    sp.add_argument("board_id", type=int)
    sp.add_argument("title")
    sp.add_argument("color", help="hex, e.g. FF0000")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_create_label)

    sp = sub.add_parser("assign-label")
    sp.add_argument("board_id", type=int)
    sp.add_argument("stack_id", type=int)
    sp.add_argument("card_id", type=int)
    sp.add_argument("label_id", type=int)
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_assign_label)

    sp = sub.add_parser("remove-label")
    sp.add_argument("board_id", type=int)
    sp.add_argument("stack_id", type=int)
    sp.add_argument("card_id", type=int)
    sp.add_argument("label_id", type=int)
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_remove_label)

    sp = sub.add_parser("label-card-by-title", help="assign a label to a card by title, creating the label first if needed")
    sp.add_argument("board_title")
    sp.add_argument("card_title")
    sp.add_argument("label_title")
    sp.add_argument("--color", help="hex, e.g. FF0000 -- required if the label doesn't exist yet")
    sp.add_argument("--from-stack", help="disambiguate when the same card title exists in more than one stack")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_label_card_by_title)

    sp = sub.add_parser("unlabel-card-by-title", help="remove a label from a card by title")
    sp.add_argument("board_title")
    sp.add_argument("card_title")
    sp.add_argument("label_title")
    sp.add_argument("--from-stack", help="disambiguate when the same card title exists in more than one stack")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_unlabel_card_by_title)

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
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
