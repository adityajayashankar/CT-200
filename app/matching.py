"""Parent-aware matching for versioned CT-200 node snapshots."""

from __future__ import annotations

from dataclasses import dataclass


def normalize_heading(value: str) -> str:
    return " ".join(value.casefold().split())


@dataclass(frozen=True)
class PriorNode:
    logical_id: str
    parent_logical_id: str | None
    heading: str


@dataclass(frozen=True)
class IncomingNode:
    source_uid: str
    parent_source_uid: str | None
    heading: str


@dataclass(frozen=True)
class Match:
    logical_id: str | None
    reason: str


def match_nodes(prior: list[PriorNode], incoming: list[IncomingNode]) -> dict[str, Match]:
    """Match only a unique normalized-heading under the matched actual parent.

    Incoming order must be parent-first (the parser provides preorder). An
    ambiguous same-title sibling is intentionally not matched: incorrectly
    preserving identity is worse than recording a new logical node.
    """
    results: dict[str, Match] = {}
    for node in incoming:
        parent_logical_id = results.get(node.parent_source_uid, Match(None, "root")).logical_id
        candidates = [
            old
            for old in prior
            if old.parent_logical_id == parent_logical_id and normalize_heading(old.heading) == normalize_heading(node.heading)
        ]
        if len(candidates) == 1:
            results[node.source_uid] = Match(candidates[0].logical_id, "unique parent-aware heading")
        elif len(candidates) > 1:
            results[node.source_uid] = Match(None, "ambiguous duplicate sibling heading")
        else:
            results[node.source_uid] = Match(None, "no matching logical node")
    return results
