"""Pure title-based lookups shared by apply-spec's resolver and the *-by-title
CLI commands. No HTTP here -- callers fetch boards/stacks/cards themselves.

Each find_* function returns None on zero matches (the caller decides what
"not found" means -- apply-spec treats it as "needs creating", the CLI
commands treat it as a fatal usage error) and raises ValueError on more than
one match. Silently picking the first match on a duplicate title is exactly
the bug this module exists to avoid -- it bit spec_resolve.py's card lookup
once already, on real data.
"""


def find_board(boards, title):
    matches = [b for b in boards if b["title"] == title]
    if len(matches) > 1:
        raise ValueError(f"board titled {title!r} is ambiguous ({len(matches)} matches)")
    return matches[0] if matches else None


def find_stack(stacks, title):
    matches = [s for s in stacks if s["title"] == title]
    if len(matches) > 1:
        raise ValueError(f"stack titled {title!r} is ambiguous ({len(matches)} matches) -- rename one or use a numeric id")
    return matches[0] if matches else None


def find_card(cards, title, from_stack=None):
    """cards must each carry a "stackTitle" key (attached by the caller when
    it flattens per-stack card lists) for from_stack filtering and ambiguity
    messages to work.
    """
    matches = [c for c in cards if c["title"] == title]
    if from_stack is not None:
        matches = [c for c in matches if c.get("stackTitle") == from_stack]
    if len(matches) > 1:
        if from_stack is None:
            stacks = [c.get("stackTitle") for c in matches]
            raise ValueError(f"card titled {title!r} is ambiguous: found in stacks {stacks} -- pass --from-stack to disambiguate")
        raise ValueError(f"card titled {title!r} is ambiguous even within stack {from_stack!r} ({len(matches)} matches)")
    return matches[0] if matches else None
