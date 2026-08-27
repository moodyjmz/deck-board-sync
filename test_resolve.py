"""Manual test file for spec_resolve.resolve -- no pytest, no CI, just run:

    python3 test_resolve.py

Covers the cases that actually matter: nothing exists yet, some things
already exist (only the gap gets created), and the "card exists but in the
wrong stack" case (must skip + warn, never silently move or duplicate).
"""

from spec_resolve import resolve

SPEC = {
    "board": {"title": "Team Workload"},
    "stacks": ["Now", "Waiting", "Done"],
    "cards": [
        {"title": "Ship the thing", "stack": "Now", "description": "..."},
        {"title": "Review the other thing", "stack": "Waiting"},
    ],
}

EMPTY_STATE = {"board": None, "stacks": [], "cards": []}


def test_empty_state_creates_everything():
    ops = resolve(EMPTY_STATE, SPEC)
    kinds = [op["op"] for op in ops]
    assert kinds.count("create_board") == 1
    assert kinds.count("create_stack") == 3
    assert kinds.count("create_card") == 2
    assert "skip_card_wrong_stack" not in kinds


def test_only_gap_is_created():
    state = {
        "board": {"id": 1, "title": "Team Workload"},
        "stacks": [{"id": 10, "title": "Now"}, {"id": 11, "title": "Waiting"}, {"id": 12, "title": "Done"}],
        "cards": [{"id": 100, "title": "Ship the thing", "stackTitle": "Now"}],
    }
    ops = resolve(state, SPEC)
    assert not any(op["op"] == "create_board" for op in ops)
    assert not any(op["op"] == "create_stack" for op in ops)
    create_cards = [op for op in ops if op["op"] == "create_card"]
    assert len(create_cards) == 1
    assert create_cards[0]["title"] == "Review the other thing"
    assert create_cards[0]["stack_id"] == 11


def test_card_in_wrong_stack_is_skipped_not_moved():
    state = {
        "board": {"id": 1, "title": "Team Workload"},
        "stacks": [{"id": 10, "title": "Now"}, {"id": 11, "title": "Waiting"}, {"id": 12, "title": "Done"}],
        "cards": [
            {"id": 100, "title": "Ship the thing", "stackTitle": "Done"},
            {"id": 101, "title": "Review the other thing", "stackTitle": "Waiting"},
        ],
    }
    ops = resolve(state, SPEC)
    create_cards = [op for op in ops if op["op"] == "create_card"]
    assert len(create_cards) == 0, "must not duplicate a card that already exists, even in the wrong stack"
    skips = [op for op in ops if op["op"] == "skip_card_wrong_stack"]
    assert len(skips) == 1
    assert skips[0]["title"] == "Ship the thing"
    assert skips[0]["existing_stack"] == "Done"
    assert skips[0]["target_stack"] == "Now"


def test_duplicate_existing_card_title_raises_instead_of_picking_one():
    # Two existing cards share a title (e.g. re-raised after being closed).
    # Silently matching one -- as the old {title: card} dict did -- risks
    # duplicating or skipping the wrong one; this must refuse instead.
    state = {
        "board": {"id": 1, "title": "Team Workload"},
        "stacks": [{"id": 10, "title": "Now"}, {"id": 11, "title": "Waiting"}, {"id": 12, "title": "Done"}],
        "cards": [
            {"id": 100, "title": "Ship the thing", "stackTitle": "Now"},
            {"id": 101, "title": "Ship the thing", "stackTitle": "Done"},
        ],
    }
    try:
        resolve(state, SPEC)
    except ValueError:
        return
    raise AssertionError("expected ValueError when a spec card's title matches two existing cards")


def test_duplicate_existing_stack_title_raises():
    bad_state = {
        "board": {"id": 1, "title": "Team Workload"},
        "stacks": [{"id": 10, "title": "Now"}, {"id": 13, "title": "Now"}, {"id": 11, "title": "Waiting"}, {"id": 12, "title": "Done"}],
        "cards": [],
    }
    try:
        resolve(bad_state, SPEC)
    except ValueError:
        return
    raise AssertionError("expected ValueError when the board already has two stacks sharing a title in spec['stacks']")


def test_unknown_target_stack_raises():
    bad_spec = {
        "board": {"title": "X"},
        "stacks": ["Now"],
        "cards": [{"title": "Orphan", "stack": "Nowhere"}],
    }
    try:
        resolve(EMPTY_STATE, bad_spec)
    except ValueError:
        return
    raise AssertionError("expected ValueError for a card targeting a stack not in spec['stacks']")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
