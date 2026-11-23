"""What each target format can express.

This module is the ceiling. Everything here is a property of a format's GRAMMAR, so no
parser, no OCR service and no model can move any of it.

On honesty: a hardcoded matrix of claims about file formats is exactly the kind of thing
that turns into folklore -- this portfolio has already caught six confident comments that
were false. So every ABSENT and APPROXIMATE entry carries a `reason` that can be checked
by argument rather than taken on trust, and the strongest ones are arithmetic:

    A pipe-table row `| a | b |` contains exactly as many cells as it has delimiters.
    So a table rendered as pipe rows must emit exactly `cols` cells in every row.
    A cell spanning two columns occupies two grid positions and carries ONE value, so
    the renderer must either emit one cell (and the row is short) or two (and one value
    is duplicated or blank). There is no third option, and it follows from the delimiter
    structure alone -- no reference implementation needed.

Where a claim rests on a specific implementation rather than on grammar, the reason says
so. `verify_claims()` re-derives the arithmetic ones at runtime.
"""

from __future__ import annotations

from .models import Expressiveness, Feature

NATIVE = Expressiveness.NATIVE
APPROX = Expressiveness.APPROXIMATE
ABSENT = Expressiveness.ABSENT


class Capability:
    """One (format, feature) claim, with the reason it holds."""

    __slots__ = ("expressiveness", "from_grammar", "reason")

    def __init__(self, expressiveness: Expressiveness, reason: str, from_grammar: bool = True):
        self.expressiveness = expressiveness
        self.reason = reason
        self.from_grammar = from_grammar
        if expressiveness is not NATIVE and not reason:
            raise ValueError("a claim of limited expressiveness must carry a reason")

    def __repr__(self) -> str:
        return f"Capability({self.expressiveness.value})"


def _native(reason: str = "") -> Capability:
    return Capability(NATIVE, reason)


# Markdown here means GFM-flavoured: CommonMark core plus pipe tables. Plain CommonMark
# has no table construct at all, which would make this matrix duller and the conclusion
# identical, so the more generous reading is used.
MARKDOWN: dict[Feature, Capability] = {
    Feature.HEADING: _native(),
    Feature.PARAGRAPH: _native(),
    Feature.LIST: _native(),
    Feature.NESTED_LIST: _native(),
    Feature.TABLE: _native(),
    Feature.MERGED_CELL: Capability(
        ABSENT,
        "a pipe row holds exactly `cols` cells, so a spanning cell must become one cell "
        "(short row) or `span` cells (a value duplicated or blanked) -- arithmetic, from "
        "the delimiter structure",
    ),
    Feature.NESTED_TABLE: Capability(
        ABSENT,
        "a pipe row is terminated by a newline and a table is made of rows, so a table "
        "cannot appear inside a cell without ending the outer row -- from the grammar",
    ),
    Feature.TABLE_IN_LIST: Capability(
        APPROX,
        "indenting a pipe table to a list item's content column is accepted by some "
        "implementations and not others, so the containment is not portable",
        from_grammar=False,
    ),
    Feature.CODE_BLOCK: _native(),
    Feature.BLOCKQUOTE: _native(),
    Feature.IMAGE: _native(),
    Feature.IMAGE_TEXT: Capability(
        ABSENT,
        "the text is pixels in a referenced file; markdown carries the reference, and no "
        "target format can carry content the source never made available as text",
    ),
    Feature.FOOTNOTE: Capability(
        APPROX,
        "footnotes are an extension, not core; renderable as a trailing list with the "
        "reference lost",
        from_grammar=False,
    ),
}

# MediaWiki markup. The interesting entry is MERGED_CELL: wiki table syntax carries HTML
# attributes on a cell, so `| colspan="2" | x` is expressible where markdown's is not.
# That single difference is why "convert everything to markdown" is not a free choice.
WIKI: dict[Feature, Capability] = {
    Feature.HEADING: _native(),
    Feature.PARAGRAPH: _native(),
    Feature.LIST: _native(),
    Feature.NESTED_LIST: _native(),
    Feature.TABLE: _native(),
    Feature.MERGED_CELL: _native(),
    Feature.NESTED_TABLE: _native(),
    Feature.TABLE_IN_LIST: Capability(
        APPROX,
        "a table inside a list item requires the item to continue across lines, which "
        "wiki markup expresses awkwardly and inconsistently",
        from_grammar=False,
    ),
    Feature.CODE_BLOCK: _native(),
    Feature.BLOCKQUOTE: _native(),
    Feature.IMAGE: _native(),
    Feature.IMAGE_TEXT: Capability(
        ABSENT,
        "the text is pixels in a referenced file, unreachable without OCR",
    ),
    Feature.FOOTNOTE: _native(),
}

# The model itself, serialised. NATIVE for everything BY CONSTRUCTION, and that is the
# point of including it: it is the control. If JSON loses nothing and markdown loses a
# merged cell, the loss cannot be blamed on the parser -- both targets were fed the same
# tree by the same code.
JSON: dict[Feature, Capability] = dict.fromkeys(Feature, _native())
JSON[Feature.IMAGE_TEXT] = Capability(
    ABSENT,
    "the one feature no target can rescue: the content is pixels, and the source never "
    "provided it as text. This is a property of the SOURCE, not of any target",
)

# Text. The control at the other end.
PLAIN: dict[Feature, Capability] = dict.fromkeys(
    Feature,
    Capability(ABSENT, "plain text has no block structure at all"),
)
PLAIN[Feature.PARAGRAPH] = _native()
PLAIN[Feature.HEADING] = Capability(
    APPROX, "a heading renders as a line of text; the LEVEL has nowhere to go"
)
PLAIN[Feature.LIST] = Capability(
    APPROX, "an item renders as a line with a marker; the grouping has nowhere to go"
)

TARGETS: dict[str, dict[Feature, Capability]] = {
    "markdown": MARKDOWN,
    "wiki": WIKI,
    "json": JSON,
    "plain": PLAIN,
}


def capability(target: str, feature: Feature) -> Capability:
    if target not in TARGETS:
        raise KeyError(f"unknown target {target!r}; known: {sorted(TARGETS)}")
    return TARGETS[target][feature]


def expressiveness(target: str, feature: Feature) -> Expressiveness:
    return capability(target, feature).expressiveness


def ceiling(target: str, features: dict[Feature, int]) -> tuple[int, int]:
    """(features that survive, features the target cannot hold) for a feature census.

    Computable BEFORE any conversion runs, from the target name and a count of what the
    corpus contains. That is what makes it a ceiling rather than a result.
    """
    survives = sum(n for f, n in features.items() if expressiveness(target, f) is NATIVE)
    lost = sum(n for f, n in features.items() if expressiveness(target, f) is not NATIVE)
    return survives, lost


def best_target(features: dict[Feature, int]) -> tuple[str, int]:
    """The target losing the fewest feature instances, ties broken by name.

    Deliberately includes `json`, which almost always wins. That is not a cop-out: it is
    the answer, and a tool that hides it in favour of a prettier format is choosing
    presentation over content on the reader's behalf.
    """
    scored = sorted((ceiling(t, features)[1], t) for t in TARGETS)
    lost, target = scored[0]
    return target, lost


def verify_claims() -> list[str]:
    """Re-derive the arithmetic claims. Returns problems; empty means the matrix holds.

    Only the grammar-derived claims can be checked this way. The three that rest on
    implementation behaviour are reported as unverifiable rather than quietly passed,
    because a claim that cannot be checked should not look like one that was.
    """
    problems: list[str] = []

    # Every non-NATIVE claim must carry a reason. Enforced in Capability.__init__, so a
    # failure here means the matrix was mutated after construction.
    for name, table in TARGETS.items():
        missing = sorted(
            f.value for f, c in table.items()
            if c.expressiveness is not NATIVE and not c.reason
        )
        if missing:
            problems.append(f"{name}: unjustified claims for {missing}")
        absent_features = set(Feature) - set(table)
        if absent_features:
            problems.append(f"{name}: no claim for {sorted(f.value for f in absent_features)}")

    # The arithmetic: a pipe row's cell count is fixed by its delimiters, so a spanning
    # cell cannot be represented. Derived here rather than asserted in a docstring.
    row = "| a | b |"
    cells_in_row = len([c for c in row.split("|") if c.strip()])
    if cells_in_row != 2:
        problems.append(f"pipe-row arithmetic wrong: {row!r} yielded {cells_in_row} cells")
    if expressiveness("markdown", Feature.MERGED_CELL) is not ABSENT:
        problems.append("markdown MERGED_CELL must be ABSENT: a pipe row has a fixed cell count")
    if expressiveness("wiki", Feature.MERGED_CELL) is not NATIVE:
        problems.append("wiki MERGED_CELL must be NATIVE: cell syntax carries HTML attributes")

    # IMAGE_TEXT must be unreachable in EVERY target, including the lossless one. It is
    # the only feature that is a property of the source rather than the target, and a
    # matrix that let json rescue it would be claiming OCR it does not do.
    for name in TARGETS:
        if expressiveness(name, Feature.IMAGE_TEXT) is NATIVE:
            problems.append(f"{name}: claims to recover text from pixels")

    # json must otherwise lose nothing, or it stops working as the control.
    lossy = sorted(
        f.value for f, c in JSON.items()
        if c.expressiveness is not NATIVE and f is not Feature.IMAGE_TEXT
    )
    if lossy:
        problems.append(f"json is meant to be the lossless control, but loses {lossy}")

    return problems


def unverifiable_claims() -> list[tuple[str, Feature, str]]:
    """Claims resting on implementation behaviour rather than grammar.

    Surfaced by `doctor` so they are visible as weaker than the rest, instead of sitting
    in the same table looking equally solid.
    """
    return [
        (name, feature, cap.reason)
        for name, table in TARGETS.items()
        for feature, cap in table.items()
        if cap.expressiveness is not NATIVE and not cap.from_grammar
    ]
