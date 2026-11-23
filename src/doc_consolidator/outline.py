"""Heading levels, and why turning them into a tree loses information.

A source document declares headings as a FLAT sequence of numbered labels: `<h1> <h3>`,
`Heading 1` / `Heading 3`, `#` / `###`, `=` / `===`. A document OUTLINE is a tree. The map
from one to the other is where the wrongness lives, and it has two independent problems.

**The skip is ambiguous.** `h1` then `h3` has two defensible readings:

    PROMOTE   the h3 is simply the h1's child, and the author typed the wrong number
    IMPLICIT  a level is genuinely missing, and the h3 sits two levels down

They produce different trees with different depths, and nothing in the source says which
was meant. Most converters silently pick one and report success.

**The map is not injective.** Under PROMOTE, `[1, 3]` and `[1, 2]` produce the SAME tree.
So the outline cannot tell you what the document declared, and two documents with
genuinely different heading structure render byte-identical outlines. `collapse_census`
measures how bad this is by brute force rather than asserting it.

Levels are therefore never rewritten in place. `Block.level` keeps what the source said,
and a reading is applied at render time and named in the output.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from .models import Block

MAX_LEVEL = 6


class Reading(StrEnum):
    """How to interpret a jump in declared heading level.

    Not called a "fix", because neither is one. Both are decisions about what the author
    meant, and they disagree.
    """

    PROMOTE = "promote"
    """A heading is a child of the nearest shallower heading, whatever number it declared.
    Skips vanish. Depth stays small and the declared numbers stop meaning anything."""

    IMPLICIT = "implicit"
    """A skipped level is a real missing level, filled with an unnamed placeholder. Depth
    matches the declared numbers and the tree contains nodes the document never had."""


class Skip(BaseModel):
    """A place where the declared level jumped by more than one."""

    model_config = ConfigDict(frozen=True)

    index: int
    from_level: int
    to_level: int
    text: str

    @property
    def gap(self) -> int:
        return self.to_level - self.from_level - 1


class OutlineNode(BaseModel):
    """A heading in the tree, with the level it DECLARED and the depth it ENDED UP AT.

    Both are kept because they can differ, and the difference is the whole point. A node
    that declared level 3 and sits at depth 2 is evidence a reading was applied.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    declared_level: int | None
    """None for a node the reading invented."""

    depth: int
    children: tuple[OutlineNode, ...] = ()

    @property
    def is_implied(self) -> bool:
        return self.declared_level is None

    def walk(self) -> list[OutlineNode]:
        out = [self]
        for child in self.children:
            out.extend(child.walk())
        return out


def find_skips(headings: tuple[Block, ...]) -> tuple[Skip, ...]:
    """Every jump of more than one level, including from the document's start.

    A document whose first heading is `h3` has skipped two levels before any content, which
    is the same ambiguity in a place people do not look for it.
    """
    out: list[Skip] = []
    previous = 0
    for i, heading in enumerate(headings):
        level = heading.level
        assert level is not None  # Block validates this
        if level > previous + 1:
            out.append(
                Skip(index=i, from_level=previous, to_level=level, text=heading.text)
            )
        previous = level
    return tuple(out)


def build_outline(
    headings: tuple[Block, ...], reading: Reading = Reading.PROMOTE
) -> tuple[OutlineNode, ...]:
    """Turn a flat heading sequence into a forest under one reading.

    Returns a forest rather than a single root, because a document with two `h1`s has two
    roots and inventing a wrapper to make it one tree would be a third silent decision.
    """
    roots: list[OutlineNode] = []
    # (node, declared_level) for the chain of open ancestors.
    stack: list[tuple[list, int]] = []

    def attach(children_list: list, node_children: list, text: str, declared: int | None,
               depth: int) -> list:
        node_slot = [text, declared, depth, node_children]
        children_list.append(node_slot)
        return node_slot

    # Build with mutable slots, freeze at the end -- OutlineNode is frozen, so the tree
    # cannot be assembled top-down.
    root_slots: list = []

    for heading in headings:
        level = heading.level
        assert level is not None

        while stack and stack[-1][1] >= level:
            stack.pop()

        if reading is Reading.IMPLICIT and stack:
            # Fill the gap between the enclosing declared level and this one.
            parent_level = stack[-1][1]
            for missing in range(parent_level + 1, level):
                parent_children = stack[-1][0]
                slot = attach(parent_children, [], "", None, len(stack) + 1)
                stack.append((slot[3], missing))
        elif reading is Reading.IMPLICIT and not stack and level > 1:
            for missing in range(1, level):
                slot = attach(root_slots, [], "", None, len(stack) + 1)
                stack.append((slot[3], missing))

        target = stack[-1][0] if stack else root_slots
        slot = attach(target, [], heading.text, level, len(stack) + 1)
        stack.append((slot[3], level))

    def freeze(slots: list) -> tuple[OutlineNode, ...]:
        return tuple(
            OutlineNode(
                text=text, declared_level=declared, depth=depth, children=freeze(kids)
            )
            for text, declared, depth, kids in slots
        )

    roots = list(freeze(root_slots))
    return tuple(roots)


def max_depth(forest: tuple[OutlineNode, ...]) -> int:
    return max((n.depth for root in forest for n in root.walk()), default=0)


def implied_nodes(forest: tuple[OutlineNode, ...]) -> int:
    """Nodes the reading invented. Zero under PROMOTE, by construction."""
    return sum(1 for root in forest for n in root.walk() if n.is_implied)


def depth_signature(forest: tuple[OutlineNode, ...]) -> tuple[int, ...]:
    """The tree's shape as a flat depth sequence.

    Two documents with the same signature have the same outline. This is what
    `collapse_census` counts distinct values of, and it is deliberately blind to text --
    the question is whether the STRUCTURE survived, not whether the words did.
    """
    out: list[int] = []

    def visit(node: OutlineNode) -> None:
        out.append(node.depth)
        for child in node.children:
            visit(child)

    for root in forest:
        visit(root)
    return tuple(out)


def collapse_census(n: int, reading: Reading = Reading.PROMOTE) -> tuple[int, int]:
    """(level sequences of length n, distinct outlines they produce). Brute force.

    This is the injectivity measurement. It is computed rather than asserted, because "the
    map is lossy" is the sort of claim that sounds obviously true and could easily be
    wrong about the size of the loss.
    """
    from itertools import product

    seen: set[tuple[int, ...]] = set()
    total = 0
    for levels in product(range(1, MAX_LEVEL + 1), repeat=n):
        total += 1
        blocks = tuple(
            Block(kind="heading", level=lv, text=f"h{i}") for i, lv in enumerate(levels)
        )
        seen.add(depth_signature(build_outline(blocks, reading)))
    return total, len(seen)
