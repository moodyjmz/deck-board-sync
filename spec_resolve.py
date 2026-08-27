"""Pure resolver for apply-spec: (current board state, spec) -> operation list.

No HTTP here on purpose -- this is the part of apply-spec where a silent bug
costs something real (duplicate cards, cards in the wrong stack), so it's
kept as a plain function that's easy to unit test and easy for --dry-run to
print in full, including operations on objects that don't exist yet.

current_state shape:
    {
        "board": {"id": ..., "title": ...} or None,
        "stacks": [{"id": ..., "title": ...}, ...],
        "cards": [{"id": ..., "title": ..., "stackTitle": ...}, ...],
    }

spec shape:
    {
        "board": {"title": ..., "color": "0082C9"},
        "stacks": ["Now", "Waiting", "Blocked", "Done"],
        "cards": [{"title": ..., "stack": "Now", "description": "..."}, ...],
    }

Returns a list of operation dicts. Real objects carry a real numeric "id";
not-yet-created ones carry a "new:<n>" placeholder id that a later operation
in the same list may reference. "skip_card_wrong_stack" entries are not
executable -- apply() should just warn on them.

Stack and card lookups go through by_title.find_stack/find_card rather than
a plain {title: item} dict, so a duplicate title on the board raises instead
of silently resolving to whichever one a dict comprehension happened to keep
last.
"""

from by_title import find_card, find_stack


def resolve(current_state, spec):
    ops = []
    counter = [0]

    def new_id():
        n = counter[0]
        counter[0] += 1
        return f"new:{n}"

    board = current_state.get("board")
    if board is None:
        board_id = new_id()
        ops.append({
            "op": "create_board",
            "id": board_id,
            "title": spec["board"]["title"],
            "color": spec["board"].get("color", "0082C9"),
        })
    else:
        board_id = board["id"]

    stack_id_by_title = {}
    for title in spec.get("stacks", []):
        existing = find_stack(current_state.get("stacks", []), title)
        if existing is not None:
            stack_id_by_title[title] = existing["id"]
        else:
            stack_id = new_id()
            ops.append({"op": "create_stack", "id": stack_id, "board_id": board_id, "title": title})
            stack_id_by_title[title] = stack_id

    for card in spec.get("cards", []):
        title = card["title"]
        target_stack = card["stack"]
        existing = find_card(current_state.get("cards", []), title)
        if existing is not None:
            if existing.get("stackTitle") != target_stack:
                ops.append({
                    "op": "skip_card_wrong_stack",
                    "title": title,
                    "existing_stack": existing.get("stackTitle"),
                    "target_stack": target_stack,
                })
            continue

        if target_stack not in stack_id_by_title:
            raise ValueError(f"card {title!r} targets stack {target_stack!r}, which is not in spec['stacks']")

        ops.append({
            "op": "create_card",
            "id": new_id(),
            "board_id": board_id,
            "stack_id": stack_id_by_title[target_stack],
            "title": title,
            "description": card.get("description"),
        })

    return ops
