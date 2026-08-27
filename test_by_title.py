"""Manual test file for by_title.py -- no pytest, no CI, just run:

    python3 test_by_title.py
"""

from by_title import find_board, find_card, find_stack

BOARDS = [{"id": 1, "title": "James"}, {"id": 2, "title": "Office"}]
STACKS = [{"id": 10, "title": "Now"}, {"id": 11, "title": "Done"}]
CARDS = [
    {"id": 100, "title": "Ship the thing", "stackTitle": "Now"},
    {"id": 101, "title": "Fix the bug", "stackTitle": "Done"},
    {"id": 102, "title": "Fix the bug", "stackTitle": "Now"},  # re-raised after being closed
]


def test_find_board_hit_and_miss():
    assert find_board(BOARDS, "James")["id"] == 1
    assert find_board(BOARDS, "Nonexistent") is None


def test_find_board_ambiguous_raises():
    dup = BOARDS + [{"id": 3, "title": "James"}]
    try:
        find_board(dup, "James")
    except ValueError:
        return
    raise AssertionError("expected ValueError for two boards sharing a title")


def test_find_stack_hit_and_miss():
    assert find_stack(STACKS, "Now")["id"] == 10
    assert find_stack(STACKS, "Nonexistent") is None


def test_find_card_unique_title_no_scope_needed():
    assert find_card(CARDS, "Ship the thing")["id"] == 100


def test_find_card_duplicate_title_without_scope_raises():
    try:
        find_card(CARDS, "Fix the bug")
    except ValueError:
        return
    raise AssertionError("expected ValueError for a title present in two stacks with no --from-stack")


def test_find_card_duplicate_title_disambiguated_by_stack():
    assert find_card(CARDS, "Fix the bug", from_stack="Done")["id"] == 101
    assert find_card(CARDS, "Fix the bug", from_stack="Now")["id"] == 102


def test_find_card_missing_returns_none():
    assert find_card(CARDS, "Does not exist") is None


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
